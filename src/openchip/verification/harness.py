"""Verification harness: lint, simulate against the reference model across seeds, synthesize.

Produces structured, tool-backed evidence. Nothing here trusts the model's opinion of
correctness; every claim is tied to a tool invocation recorded in the evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ..config import Config
from ..contracts.schema import Contract
from ..tools import iverilog, verilator, yosys
from ..tools.base import ToolResult
from .formal import run_formal
from .sandbox import run_isolated
from .rtl_policy import check_rtl
from .testbench import dump_contract_json, generate_testbench, write_vectors

REFGEN = Path(__file__).with_name("refgen.py")
REFLINT = Path(__file__).with_name("reflint.py")
MISMATCH_RE = re.compile(r"MISMATCH cycle=(\d+) port=(\w+) expected=([0-9a-fA-Fx]+) got=([0-9a-fA-FxXzZ]+)")


@dataclass
class SimSeedResult:
    seed: int
    cycles: int
    status: str  # pass | fail | reference_error | compile_error | sim_error | timeout
    mismatches: int = 0
    first_mismatches: list[dict] = field(default_factory=list)
    detail: str = ""
    sampling: str = ""


@dataclass
class VerificationResult:
    stage: str  # which stage was reached: reference | lint | compile | simulate | synth | done
    accepted: bool
    lint: Optional[dict] = None
    compile: Optional[dict] = None
    sims: list[dict] = field(default_factory=list)
    synth: Optional[dict] = None
    formal: Optional[dict] = None
    guard_findings: list[dict] = field(default_factory=list)
    reference_error: str = ""
    summary: str = ""
    artifacts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def evidence_for_model(self, max_chars: int = 6000) -> str:
        """Compact evidence text for the repair prompt."""
        parts = []
        for g in self.guard_findings:
            parts.append("ACCEPTANCE GUARD (deterministic contract-vs-RTL check): " + g["message"])
        if self.reference_error:
            parts.append("REFERENCE MODEL ERROR (the reference, not the RTL, failed to run):\n" + self.reference_error)
        if self.lint and not self.lint.get("ok"):
            parts.append("VERILATOR LINT:\n" + _fmt_diags(self.lint))
        if self.compile and not self.compile.get("ok"):
            parts.append("IVERILOG COMPILE:\n" + _fmt_diags(self.compile))
        for s in self.sims:
            if s["status"] == "fail":
                lines = [f"SIMULATION seed={s['seed']}: {s['mismatches']} mismatching cycles out of {s['cycles']}. First mismatches (cycle numbers count from the first recorded comparison after the startup sequence; expected = reference model; got=x/X/z means the RTL output is undefined — an uninitialized register, missing reset assignment, or unassigned wire):"]
                if s.get("sampling"):
                    lines.append(s["sampling"])
                first = next(iter(s["first_mismatches"]), {})
                if first.get("preceding"):
                    lines.append("Preceding stimulus before the first mismatch (decimal values; expected outputs are reference predictions, not observed DUT outputs):")
                    lines += [f"  cycle {v['cycle']}: inputs={v['inputs']} expected={v['expected']}" for v in first["preceding"]]
                lines += [f"  cycle {m['cycle']}: {m['port']} expected=0x{m['expected']} got=0x{m['got']}" + (f"  inputs: {m['inputs']}" if m.get("inputs") else "") for m in s["first_mismatches"][:12]]
                parts.append("\n".join(lines))
            elif s["status"] not in ("pass",):
                parts.append(f"SIMULATION seed={s['seed']}: {s['status']}: {s['detail'][:800]}")
        if self.synth and not self.synth.get("ok"):
            parts.append("YOSYS SYNTHESIS:\n" + _fmt_diags(self.synth))
        if self.formal and self.formal.get("status") == "counterexample":
            parts.append(f"FORMAL (SBY bounded model check, depth {self.formal.get('depth')}): counterexample for assertion {self.formal.get('failed_assert', '?')} in the property checker. Either the RTL violates the contract or the checker misreads it; the simulation evidence above is authoritative when they disagree.")
        text = "\n\n".join(parts) or self.summary
        return text[:max_chars]


def _fmt_diags(d: dict) -> str:
    diags = d.get("diagnostics") or []
    if diags:
        return "\n".join(f"  {x.get('kind','')} {x.get('file','')}:{x.get('line','')}: {x.get('message','')}" for x in diags[:15])
    return d.get("tail", "")[:1500]


def _tr(r: ToolResult, keep_tail: int = 30) -> dict:
    return {"ok": r.ok, "tool": r.tool, "argv": r.argv, "exit_code": r.exit_code, "duration_s": r.duration_s,
            "timed_out": r.timed_out, "version": r.version, "error": r.error, "tail": r.tail(keep_tail),
            **{k: v for k, v in r.extra.items()}}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _archive_previous_reference_output(out: Path) -> None:
    """Keep old evidence, but require the current subprocess to create its output.

    CLI re-verification and resumed attempts reuse filenames. A subprocess killed
    before writing must not inherit the previous reference's successful result.
    """
    if out.exists():
        previous = Path(tempfile.mkdtemp(prefix=f".{out.stem}-previous-", dir=out.parent))
        out.replace(previous / out.name)


def run_reference(reference_py: Path, contract_json: Path, seed: int, cycles: int, out: Path, python: str = sys.executable, timeout_s: float = 180.0,
                  replay: Optional[Path] = None) -> dict:
    _archive_previous_reference_output(out)
    try:
        proc = run_isolated(REFGEN, [Path(reference_py), Path(contract_json), str(seed), str(cycles), out]
                            + ([Path(replay)] if replay else []), out, python=python, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        return {"error": f"reference model timed out after {timeout_s}s (infinite loop?)"}
    if proc.returncode != 0:
        return {"error": f"reference generator exited with code {proc.returncode}: {(proc.stderr or '')[-800:]}"}
    if not out.is_file():
        return {"error": f"reference generator produced no output (exit {proc.returncode}): {(proc.stderr or '')[-800:]}"}
    return json.loads(out.read_text())


def lint_reference_timing(reference_py: Path, contract_json: Path, out: Path, seed: int = 7, steps: int = 40, python: str = sys.executable, timeout_s: float = 120.0) -> dict:
    """Return {"violations": [...], "checked_steps": n, "error": str}. A violation means a `registered`
    output of the reference depends on same-cycle inputs."""
    _archive_previous_reference_output(out)
    try:
        proc = run_isolated(REFLINT, [Path(reference_py), Path(contract_json), str(seed), str(steps), out],
                            out, python=python, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        return {"violations": [], "checked_steps": 0, "error": "timing lint timed out"}
    if proc.returncode != 0:
        return {"violations": [], "checked_steps": 0,
                "error": f"timing lint exited with code {proc.returncode}"}
    if not out.is_file():
        return {"violations": [], "checked_steps": 0, "error": "timing lint produced no output"}
    return json.loads(out.read_text())


def compare_references(contract: Contract, ref_a: Path, ref_b: Path, work: Path, seeds: list[int], cycles: int) -> dict:
    """Run two references on identical stimulus (generated by ref_a) and count differing cycles.
    Returns {"error": ..} if either fails, else {"mismatches": n, "cycles": total, "first": [...]}."""
    work.mkdir(parents=True, exist_ok=True)
    cj = work / "contract.json"
    dump_contract_json(contract, cj)
    total = 0
    mism = 0
    first: list[dict] = []
    for seed in seeds:
        va = run_reference(ref_a, cj, seed, cycles, work / f"a_{seed}.json")
        if va.get("error"):
            return {"error": "reference A: " + va["error"], "who": "a"}
        vb = run_reference(ref_b, cj, seed, cycles, work / f"b_{seed}.json", replay=work / f"a_{seed}.json")
        if vb.get("error"):
            return {"error": "reference B: " + vb["error"], "who": "b"}
        for cyc, (oa, ob) in enumerate(zip(va["outputs"], vb["outputs"])):
            total += 1
            if oa != ob:
                mism += 1
                if len(first) < 10:
                    diff = {k: (oa[k], ob.get(k)) for k in oa if oa[k] != ob.get(k)}
                    first.append({"seed": seed, "cycle": cyc, "inputs": va["inputs"][cyc], "a_vs_b": diff})
    return {"mismatches": mism, "cycles": total, "first": first}


def verify(contract: Contract, rtl_path: Path, reference_py: Path, work: Path, cfg: Config,
           cycles: Optional[int] = None, seeds: Optional[list[int]] = None, run_synth: Optional[bool] = None,
           props_path: Optional[Path] = None) -> VerificationResult:
    work.mkdir(parents=True, exist_ok=True)
    cycles = cycles or cfg.verification.sim_cycles
    seeds = seeds or cfg.verification.seeds
    run_synth = cfg.verification.require_synth if run_synth is None else run_synth
    tcfg = cfg.tools
    contract_json = work / "contract.json"
    dump_contract_json(contract, contract_json)
    res = VerificationResult(stage="reference", accepted=False)
    res.artifacts = {"rtl": str(rtl_path), "rtl_sha256": sha256_file(rtl_path), "reference": str(reference_py),
                     "reference_sha256": sha256_file(reference_py), "contract_digest": contract.digest()}

    findings, policy = check_rtl(rtl_path, work, tcfg.iverilog, tcfg.timeout_s)
    (work / "rtl-policy.json").write_text(json.dumps(policy, indent=2))
    if findings:
        res.stage = "rtl_policy"
        res.guard_findings = findings
        res.summary = "RTL is outside the supported synthesizable subset"
        return res
    if cfg.verification.require_formal and (not cfg.verification.run_formal or
            contract.combinational or props_path is None or not props_path.is_file()):
        res.stage = "formal"
        res.summary = "required formal verification is unavailable"
        return res

    # 1. reference vectors for every seed (a broken reference is reported, not blamed on RTL)
    vectors = {}
    for seed in seeds:
        vec = run_reference(reference_py, contract_json, seed, cycles, work / f"vectors_{seed}.json")
        if vec.get("error"):
            res.reference_error = vec["error"]
            res.summary = "reference model failed to execute"
            return res
        vectors[seed] = vec
        write_vectors(vec, contract, work / f"vectors_in_{seed}.hex", work / f"vectors_exp_{seed}.hex")

    # 2. lint
    res.stage = "lint"
    lint = verilator.lint([rtl_path.name], contract.module_name, rtl_path.parent, tcfg.verilator, tcfg.timeout_s)
    res.lint = _tr(lint)
    # -Wno-fatal keeps warnings nonfatal. Every nonzero exit is a failure,
    # including namespace startup, crashes, and diagnostics we cannot parse.
    if cfg.verification.require_lint and not res.lint["ok"]:
        res.summary = "verilator lint failed"
        return res

    # 3. compile RTL + generated testbench
    res.stage = "compile"
    tb = work / f"tb_{contract.module_name}.v"
    tb.write_text(generate_testbench(contract, cycles))
    res.artifacts["testbench"] = str(tb)
    comp = iverilog.compile_verilog([str(rtl_path.resolve()), tb.name], f"tb_{contract.module_name}", "sim.vvp", work, tcfg.iverilog, tcfg.timeout_s)
    res.compile = _tr(comp)
    if not comp.ok:
        res.summary = "iverilog compile failed"
        return res

    # 4. simulate per seed
    res.stage = "simulate"
    all_pass = True
    for seed in seeds:
        sim = iverilog.simulate("sim.vvp", work, tcfg.vvp, tcfg.timeout_s,
                                plusargs=[f"+vin=vectors_in_{seed}.hex", f"+vexp=vectors_exp_{seed}.hex"])
        sr = parse_sim(sim, seed, cycles, vectors[seed])
        sr.sampling = ("Sampling: combinational outputs are compared after current inputs settle."
                       if contract.combinational else
                       "Sampling: outputs are compared BEFORE the active clock edge, after current inputs settle. "
                       "State reflects preceding cycles' inputs; current inputs affect the upcoming edge. "
                       "Combinational outputs may respond immediately to current inputs.")
        if contract.clock_reset and contract.clock_reset.reset is None:
            sr.sampling += " No reset: comparison begins after three zero-data conditioning edges; DUT startup state is not initialized and X/Z still fails."
        res.sims.append(asdict(sr))
        (work / f"sim_{seed}.log").write_text(sim.stdout + sim.stderr)
        if sr.status != "pass":
            all_pass = False
    if not all_pass:
        res.summary = "simulation mismatches against reference model"
        return res

    # 5. synthesis check
    if run_synth:
        res.stage = "synth"
        syn = yosys.synth_generic([str(rtl_path.resolve())], contract.module_name, work, tcfg.yosys, tcfg.timeout_s)
        res.synth = _tr(syn)
        if not syn.ok:
            res.summary = "yosys generic synthesis failed"
            return res

    # 6. formal (bounded model checking against the independent property checker)
    formal_note = "; formal not run"
    if props_path is not None and props_path.is_file() and cfg.verification.run_formal and not contract.combinational:
        res.stage = "formal"
        fr = run_formal(contract, rtl_path, props_path, work / "formal", tcfg.sby, cfg.verification.formal_depth, cfg.verification.formal_timeout_s)
        res.formal = _tr(fr)
        res.artifacts["properties"] = str(props_path)
        res.artifacts["properties_sha256"] = sha256_file(props_path)
        st = fr.extra.get("status")
        formal_note = f"; formal BMC depth {cfg.verification.formal_depth}: {st}"
        if st == "counterexample":
            res.summary = "formal counterexample requires review of the RTL or property checker"
            return res
        if cfg.verification.require_formal and (st != "bounded_pass" or not fr.ok):
            res.summary = f"required formal verification failed: {st}"
            return res

    res.stage = "done"
    res.accepted = True
    res.summary = f"lint ok; simulation passed for seeds {seeds} x {cycles} cycles" + ("; generic synthesis ok" if run_synth else "; synthesis not run") + formal_note
    return res


def parse_sim(sim: ToolResult, seed: int, cycles: int, vec: dict) -> SimSeedResult:
    text = sim.stdout + sim.stderr
    if sim.timed_out:
        return SimSeedResult(seed, cycles, "timeout", detail="simulator exceeded its time limit")
    if not sim.ok:
        return SimSeedResult(seed, cycles, "sim_error", detail=sim.tail(20))
    if "RESULT TIMEOUT" in text:
        return SimSeedResult(seed, cycles, "timeout", detail="testbench watchdog fired (clock or reset never advanced?)")
    mm = []
    for m in MISMATCH_RE.finditer(text):
        cyc = int(m.group(1))
        mm.append({"cycle": cyc, "port": m.group(2), "expected": m.group(3), "got": m.group(4),
                   "inputs": vec["inputs"][cyc] if cyc < len(vec["inputs"]) else {},
                   "preceding": [{"cycle": i, "inputs": vec["inputs"][i], "expected": vec["outputs"][i]}
                                 for i in range(max(0, cyc - 4), min(cyc, len(vec["inputs"]), len(vec.get("outputs", []))))]})
    m = re.search(r"RESULT FAIL mismatches=(\d+)", text)
    if m:
        return SimSeedResult(seed, cycles, "fail", int(m.group(1)), mm)
    passes = re.findall(r"^RESULT PASS cycles=(\d+)$", text, re.M)
    if len(passes) == 1 and int(passes[0]) == cycles and not mm:
        return SimSeedResult(seed, cycles, "pass")
    return SimSeedResult(seed, cycles, "sim_error", detail=sim.tail(20))
