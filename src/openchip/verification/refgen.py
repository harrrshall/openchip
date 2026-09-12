"""Vector generator: runs an (untrusted) reference model in an isolated subprocess.

Invoked as: python -I refgen.py <reference.py> <contract.json> <seed> <cycles> <out.json> [replay_inputs.json]
With a replay file, the recorded per-cycle inputs are used instead of the stimulus generator.
Emits per-cycle inputs and expected outputs. Any exception is reported as a structured error
so the runtime can distinguish a broken reference from a broken RTL.
"""
from __future__ import annotations

import importlib.util
import json
import random
import resource
import sys
import traceback


def _limits() -> None:
    try:
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ref_path, contract_path, seed, cycles, out_path = sys.argv[1:6]
    replay = json.load(open(sys.argv[6]))["inputs"] if len(sys.argv) > 6 else None
    seed, cycles = int(seed), int(cycles)
    if replay is not None:
        cycles = len(replay)
    _limits()
    contract = json.load(open(contract_path))
    cr = contract.get("clock_reset") or {}
    params = {p["name"]: p["default"] for p in contract["parameters"]}
    data_in = [p for p in contract["ports"] if p["direction"] == "input" and p["name"] not in (cr.get("clock"), cr.get("reset"))]
    outs = [p for p in contract["ports"] if p["direction"] == "output"]
    # Reset/clock are driven by the harness; they are passed to step() at their inactive/idle
    # values so a reference that reads them keeps working.
    rst_inactive = 0 if cr.get("reset_active", "high") == "high" else 1
    result = {"seed": seed, "cycles": cycles, "params": params, "inputs": [], "outputs": [], "error": ""}
    try:
        spec = importlib.util.spec_from_file_location("reference", ref_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        ref = mod.Reference(params)
        ref.reset()
        stim = getattr(mod, "stimulus", None)
        if stim is None and callable(getattr(ref, "stimulus", None)):
            stim = ref.stimulus
        rng = random.Random(seed)
        prev = {o["name"]: 0 for o in outs}
        for cyc in range(cycles):
            vec = None
            if replay is not None:
                vec = dict(replay[cyc])
            elif stim is not None:
                vec = stim(rng, cyc, params, dict(prev))
            if vec is None:
                vec = {p["name"]: rng.getrandbits(p["width"]) for p in data_in}
            clean = {}
            for p in data_in:
                v = vec.get(p["name"], 0)
                if not isinstance(v, int):
                    raise TypeError(f"stimulus for {p['name']} at cycle {cyc} is not an int")
                clean[p["name"]] = v & ((1 << p["width"]) - 1)
            step_in = dict(clean)
            if cr:
                if cr.get("reset"):
                    step_in[cr["reset"]] = rst_inactive
                step_in[cr["clock"]] = 0
            o = ref.step(step_in)
            if not isinstance(o, dict):
                raise TypeError(f"step() returned {type(o).__name__}, expected dict")
            expected = {}
            for p in outs:
                if p["name"] not in o:
                    raise KeyError(f"step() did not return output {p['name']} at cycle {cyc}")
                v = o[p["name"]]
                if not isinstance(v, int):
                    raise TypeError(f"output {p['name']} at cycle {cyc} is {type(v).__name__}, expected int")
                expected[p["name"]] = v & ((1 << p["width"]) - 1)
            result["inputs"].append(clean)
            result["outputs"].append(expected)
            prev = expected
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc().strip().splitlines()
        result["error"] = f"{type(e).__name__}: {e}\n" + "\n".join(tb[-6:])
    with open(out_path, "w") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
