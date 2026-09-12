"""Check the composed development demo against the separate Verilog oracle.

Run on JarvisLabs after compose finishes; this file and its oracle are never
included in runtime-model prompts.
"""
import json
import sys
from pathlib import Path

from openchip.tools import iverilog
from openchip.verification.harness import sha256_file

project = Path(sys.argv[1]).resolve()
oracle = Path(sys.argv[2]).resolve()
outcome = json.loads((project / "outcome.json").read_text())
integration = outcome.get("integration") or {}
artifacts = integration.get("artifacts") or {}
if not artifacts.get("rtl"):
    raise SystemExit("No assembled RTL was delivered; independent check cannot run.")
rtl = Path(artifacts["rtl"])
if sha256_file(rtl) != artifacts["rtl_sha256"]:
    raise SystemExit("Delivered RTL differs from its recorded evidence.")
work = project / "independent-check"
work.mkdir(exist_ok=False)
compiled = iverilog.compile_verilog([str(rtl), str(oracle)], "tb", "oracle.vvp", work)
simulation = iverilog.simulate("oracle.vvp", work) if compiled.ok else None
prompts = list((project / "integration" / "reference").glob("prompt-*.json"))
messages = [json.loads(p.read_text()) for p in prompts]
prompt_text = "\n".join(m["system"] + "\n" + m["user"] for m in messages)
leaks = []
for leaf in (project / "leaves").iterdir():
    if str(leaf) in prompt_text:
        leaks.append(str(leaf))
    for folder, suffix in (("rtl", "*.v"), ("reference", "*.py")):
        for artifact in (leaf / folder).glob(suffix):
            text = artifact.read_text().strip()
            if text and text in prompt_text:
                leaks.append(str(artifact))
result = {
    "compile_ok": compiled.ok,
    "simulation_ok": bool(simulation and simulation.ok and "PASS cases=" in simulation.stdout),
    "log": (simulation.stdout + simulation.stderr) if simulation else compiled.stdout + compiled.stderr,
    "rtl_sha256": sha256_file(rtl), "oracle_sha256": sha256_file(oracle),
    "system_reference_prompt_count": len(prompts), "leaf_artifact_leaks": leaks,
    "reference_context_checked": bool(prompts) and not leaks,
    "scope": "independent development oracle; not the held-out M4 gate",
}
(work / "result.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["simulation_ok"] and result["reference_context_checked"] else 1)
