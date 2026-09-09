"""Deterministic timing lint for a reference model (runs isolated, like refgen).

For every output the contract declares `registered`, the value returned by step(k) must not depend on
the inputs passed to step(k): replay an identical prefix, then feed two different input vectors at
step k and compare. A difference proves the reference computes a registered output combinationally —
the most common reference error observed in evaluation. Combinational outputs are not checked.

Invoked as: python -I reflint.py <reference.py> <contract.json> <seed> <steps> <out.json>
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
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ref_path, contract_path, seed, steps, out_path = sys.argv[1:6]
    seed, steps = int(seed), int(steps)
    _limits()
    contract = json.load(open(contract_path))
    cr = contract.get("clock_reset") or {}
    params = {p["name"]: p["default"] for p in contract["parameters"]}
    data_in = [p for p in contract["ports"] if p["direction"] == "input" and p["name"] not in (cr.get("clock"), cr.get("reset"))]
    registered = [p["name"] for p in contract["ports"] if p["direction"] == "output" and p.get("timing", "registered") == "registered"] if cr else []
    result = {"violations": [], "checked_steps": 0, "error": ""}
    if not registered or not data_in:
        json.dump(result, open(out_path, "w"))
        return 0
    try:
        spec = importlib.util.spec_from_file_location("reference", ref_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        rng = random.Random(seed)
        rst_inactive = 0 if cr.get("reset_active", "high") == "high" else 1

        def rand_vec():
            v = {p["name"]: rng.getrandbits(p["width"]) for p in data_in}
            v[cr["reset"]] = rst_inactive
            v[cr["clock"]] = 0
            return v

        prefix = [rand_vec() for _ in range(steps)]
        seen = {}
        for k in range(steps):
            a = mod.Reference(dict(params)); a.reset()
            b = mod.Reference(dict(params)); b.reset()
            for j in range(k):
                a.step(dict(prefix[j])); b.step(dict(prefix[j]))
            alt = rand_vec()
            if all(alt[p["name"]] == prefix[k][p["name"]] for p in data_in):
                # force a difference on one input
                p0 = data_in[rng.randrange(len(data_in))]
                alt[p0["name"]] = (alt[p0["name"]] ^ 1) & ((1 << p0["width"]) - 1)
            oa = a.step(dict(prefix[k]))
            ob = b.step(dict(alt))
            result["checked_steps"] += 1
            for name in registered:
                if oa.get(name) != ob.get(name) and name not in seen:
                    diff = {p["name"]: (prefix[k][p["name"]], alt[p["name"]]) for p in data_in if prefix[k][p["name"]] != alt[p["name"]]}
                    seen[name] = True
                    result["violations"].append({"output": name, "step": k, "value_a": oa.get(name), "value_b": ob.get(name), "inputs_differ": diff})
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc().strip().splitlines()
        result["error"] = f"{type(e).__name__}: {e}\n" + "\n".join(tb[-4:])
    json.dump(result, open(out_path, "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
