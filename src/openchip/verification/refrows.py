"""Evaluate a reference model on a fixed list of input vectors (runs isolated, like refgen/reflint).

Each vector is evaluated on a freshly constructed, freshly reset Reference, so a stateful reference
cannot leak one row's history into the next: the caller only ever asks this of combinational
contracts, and an independent instance per row is what makes that assumption checkable.

Invoked as: python -I refrows.py <reference.py> <contract.json> <rows.json> <out.json>
  rows.json: {"rows": [{"<port>": <int>, ...}, ...], "outputs": ["<port>", ...],
              "mode": "rows" | "sequence" | "sequences"}
              # sequence:  one Reference, reset once, then step through `rows` in order
              # sequences: `rows` is a list of sequences; each gets its own freshly reset Reference
  out.json:  {"results": [{"<port>": <int>, ...}, ...], "error": "..."}
             # "sequences" mode: results is a list of lists, one per sequence
"""
from __future__ import annotations

import importlib.util
import json
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
    ref_path, contract_path, rows_path, out_path = sys.argv[1:5]
    _limits()
    result: dict = {"results": [], "error": ""}
    try:
        contract = json.load(open(contract_path))
        params = {p["name"]: p["default"] for p in contract.get("parameters", [])}
        spec_ = json.load(open(rows_path))
        rows = spec_["rows"]
        outputs = spec_["outputs"]
        spec = importlib.util.spec_from_file_location("reference", ref_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        if spec_.get("mode") == "sequences":
            for seq in rows:
                ref = mod.Reference(dict(params))
                ref.reset()
                steps = []
                for row in seq:
                    out = ref.step(dict(row))
                    steps.append({k: out.get(k) for k in outputs})
                result["results"].append(steps)
        elif spec_.get("mode") == "sequence":
            ref = mod.Reference(dict(params))
            ref.reset()
            for row in rows:
                out = ref.step(dict(row))
                result["results"].append({k: out.get(k) for k in outputs})
        else:
            for row in rows:
                ref = mod.Reference(dict(params))
                ref.reset()
                out = ref.step(dict(row))
                result["results"].append({k: out.get(k) for k in outputs})
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc().strip().splitlines()
        result["error"] = f"{type(e).__name__}: {e}\n" + "\n".join(tb[-4:])
    json.dump(result, open(out_path, "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
