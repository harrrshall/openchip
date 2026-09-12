"""Build and verify a two-module arithmetic assembly on JarvisLabs.

Run: PYTHONPATH=src python examples/composition_demo.py /home/openchip-runs/assembly-demo
This is a hand-specified assembly demonstration, not autonomous M4 acceptance.
"""
import copy
import json
import sys
from pathlib import Path

from openchip.cli.main import main
from openchip.config import Config
from openchip.contracts.schema import Contract
from openchip.contracts.system import SystemContract, render_top
from openchip.verification.harness import verify


def contract(name, operation, width=8, parameterized=True):
    return Contract.model_validate({
        "module_name": name, "purpose": operation, "clock_reset": None,
        "parameters": [{"name": "WIDTH", "default": width, "min": 1, "max": 32}] if parameterized else [],
        "ports": [dict(name=n, direction=d, width=width, timing="combinational",
                       width_expr="WIDTH" if parameterized else None)
                  for n, d in [("a", "input"), ("b", "input"), ("y", "output")]],
        "behavior": operation + ". All arithmetic is unsigned modulo two to the port width. "
                    "This is a combinational design with no internal state, clock or reset. "
                    "Outputs respond to current input values without a clock delay.",
        "requirements": [{"id": "R001", "text": operation, "source": "user_text"}],
    })


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    add = contract("adder", "Output y equals the sum of inputs a and b")
    sub = contract("subtract", "Output y equals input a minus input b")
    top = contract("arithmetic_pair", "Output y equals input b after addition and subtraction", 4, False)
    top.ports.append(top.ports[-1].model_copy(update={"name": "sum"}))
    top.requirements[0].text = "Output sum is (a+b) modulo 16 and output y is b."
    top.behavior = ("The sum output is (a+b) modulo 16. The y output is b, recovered by "
                    "subtracting a from the modular sum. Both outputs depend only on current "
                    "four-bit unsigned inputs. There is no state, clock, reset or latency.")

    def instance(name, leaf):
        return dict(name=name, contract=leaf.model_dump(mode="json"), version=leaf.version,
                    digest=leaf.digest(), parameters={"WIDTH": 4})

    def wire(fm, fp, tm, tp):
        return dict(from_module=fm, from_port=fp, to_module=tm, to_port=tp, width=4)

    data = dict(top=top.model_dump(mode="json"), modules=[instance("add", add), instance("sub", sub)],
                integration_requirements=["R001"], connections=[
                    wire("TOP", "a", "add", "a"), wire("TOP", "b", "add", "b"),
                    wire("add", "y", "sub", "a"), wire("TOP", "a", "sub", "b"),
                    wire("add", "y", "TOP", "sum"), wire("sub", "y", "TOP", "y"),
                ])
    system = SystemContract.model_validate(data)
    spec = out / "system.json"
    spec.write_text(system.model_dump_json(indent=2))
    main(["assemble", "--system", str(spec), "--out", str(out / "top.v")])
    leaves = ("module adder #(parameter WIDTH=8)(input [WIDTH-1:0] a,b, output [WIDTH-1:0] y); "
              "assign y=a+b; endmodule\n"
              "module subtract #(parameter WIDTH=8)(input [WIDTH-1:0] a,b, output [WIDTH-1:0] y); "
              "assign y=a-b; endmodule\n")
    (out / "leaves.v").write_text(leaves)
    rtl = out / "arithmetic_pair.v"
    rtl.write_text((out / "top.v").read_text() + leaves)
    reference = out / "reference.py"
    reference.write_text(
        "class Reference:\n"
        "    def __init__(self, params): pass\n"
        "    def reset(self): pass\n"
        "    def step(self, i): return {'sum': (i['a']+i['b']) & 15, 'y': i['b']}\n"
        "def stimulus(rng, cycle, params, prev): return {'a': cycle & 15, 'b': (cycle >> 4) & 15}\n"
    )
    result = verify(top, rtl, reference, out / "verify", Config(), cycles=256, seeds=[1])
    (out / "evidence.json").write_text(json.dumps(result.to_dict(), indent=2))
    assert result.accepted, result.summary
    rejected = {}
    for fault in ["floating", "multiple_drivers", "width", "stale_digest", "signedness", "cycle"]:
        bad = copy.deepcopy(data)
        if fault == "floating":
            bad["connections"].pop(0)
        elif fault == "multiple_drivers":
            bad["connections"].append(wire("TOP", "b", "add", "a"))
        elif fault == "width":
            bad["modules"][0]["parameters"]["WIDTH"] = 8
        elif fault == "stale_digest":
            bad["modules"][0]["contract"]["purpose"] = "Changed without refreshing the pin"
        elif fault == "signedness":
            bad["top"]["ports"][0]["signed"] = True
        else:
            bad["connections"][0] = wire("sub", "y", "add", "a")
        try:
            SystemContract.model_validate(bad)
        except ValueError as exc:
            rejected[fault] = str(exc)
        else:
            raise AssertionError(f"structural fault accepted: {fault}")
    # Swap subtract's input ports. Widths are legal; only behavior reveals this.
    swapped = copy.deepcopy(data)
    swapped["connections"][2]["to_port"] = "b"
    swapped["connections"][3]["to_port"] = "a"
    bad_rtl = out / "swapped.v"
    bad_rtl.write_text(render_top(SystemContract.model_validate(swapped)) + leaves)
    bad = verify(top, bad_rtl, reference, out / "swapped", Config(), cycles=256, seeds=[1])
    (out / "swapped-evidence.json").write_text(json.dumps(bad.to_dict(), indent=2))
    assert not bad.accepted and bad.stage == "simulate", bad.summary
    summary = dict(assembly_accepted=result.accepted, input_pairs=256,
                   structural_rejections=rejected, structural_faults=6,
                   swapped_connection_rejected=True, scope="hand-specified structural demonstration; M4 gate not met")
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "structural_rejections"}, indent=2))


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
