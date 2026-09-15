"""Harness matrix: overlay merge, and one end-to-end run on a fake adapter.

No network and no EDA tools: the innermost pipeline call is injected, so what is exercised is the
matrix machinery itself (cell expansion, per-cell directories and record.json, error capture,
resumability) plus the scoreboard maths.
"""
import json
from pathlib import Path

import pytest

from openchip.config import Config
from openchip.evals.harnesses import apply_overlay, deep_merge, get_harness
from openchip.evals.matrix import MatrixSpec, run_matrix
from openchip.evals.scoreboard import build_scoreboard, mcnemar_exact, wilson
from openchip.models.adapter import ModelResponse, Usage


# --------------------------------------------------------------------------- overlay / registry
def test_overlay_merge_is_deep_and_validated():
    base = Config.load()
    assert base.review.enabled is True
    cfg = apply_overlay(base, {"review": {"enabled": False}, "model": {"model": "x/y"}})
    assert cfg.review.enabled is False and cfg.model.model == "x/y"
    # sibling fields inside a touched sub-config survive the merge
    assert cfg.verification.seeds == base.verification.seeds
    assert cfg.model.temperature == base.model.temperature
    assert base.review.enabled is True and base.model.model != "x/y"   # base untouched
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}}) == {"a": {"b": 1, "c": 3}}
    with pytest.raises(Exception):
        apply_overlay(base, {"verification": {"seeds": "not-a-list"}})

    assert get_harness("no-corroborate").config(base).verification.corroborate is False
    assert get_harness("no-formal").config(base).verification.run_formal is False
    assert get_harness("direct").mode == "direct"
    alt = get_harness("alt-ref").config(base, {"model": "other/model", "provider": "openrouter"})
    assert alt.model.alt is not None and alt.model.alt.model == "other/model"
    with pytest.raises(ValueError):
        get_harness("alt-ref").config(base, None)
    with pytest.raises(KeyError):
        get_harness("nope")


# --------------------------------------------------------------------------- end to end
class FakeAdapter:
    """Minimal stand-in for ModelAdapter: canned reply, real Usage accounting."""

    def __init__(self, text="```verilog\nmodule TopModule(); endmodule\n```"):
        self.text = text
        self.usage = Usage()

    def chat(self, messages, role="generic", **kw):
        r = ModelResponse(text=self.text, reasoning="", finish_reason="stop", prompt_tokens=40,
                          completion_tokens=60, latency_s=0.01, model="fake")
        self.usage.add(role, r)
        return r


def _spec_file(tmp_path, harnesses=("baseline", "no-review"), repeats=2):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    for i in range(3):
        (dataset / f"Prob00{i}_fake_prompt.txt").write_text(f"build fake module {i}\n")
    spec = tmp_path / "matrix.toml"
    spec.write_text(
        f'out_root = "{tmp_path / "out"}"\nrepeats = {repeats}\nbudget = "10s"\nconcurrency = 3\n'
        f'harnesses = {json.dumps(list(harnesses))}\n\n'
        f'[dataset]\npath = "{dataset}"\n\n'
        '[[models]]\nname = "fake-model"\nprovider = "openai-compatible"\n'
        'base_url = "http://127.0.0.1:9/v1"\nmodel = "fake/model"\nmax_concurrency = 2\n')
    return spec


def test_matrix_run_records_resumes_and_survives_a_cell_exception(tmp_path):
    spec = MatrixSpec.load(_spec_file(tmp_path))
    adapter = FakeAdapter()
    seen = []

    def fake_execute(cfg, cell, problem, work, budget_s, log):
        seen.append(cell.label())
        if cell.problem.startswith("Prob001"):
            raise RuntimeError("injected cell failure")
        adapter.chat([{"role": "user", "content": problem["prompt"]}], role="rtl")
        work.mkdir(parents=True, exist_ok=True)
        # Prob000 passes everywhere; Prob002 is a false acceptance under no-review only.
        passing = cell.problem.startswith("Prob000")
        accepted = passing or cell.harness.name == "no-review"
        return {"id": cell.problem, "state": "completed", "accepted": accepted,
                "status": "pass" if passing else "fail", "attempts": 1, "calls": 1,
                "tokens": 100, "wall_s": 1.0}

    res = run_matrix(spec, log=lambda m: None, execute=fake_execute)
    root = Path(res["root"])
    assert res["cells"] == 12 and res["done"] == 12 and res["errors"] == 4  # 3 problems x 2 harnesses x 2 reps
    assert len(seen) == 12 and root.parent == tmp_path / "out"

    cell_dir = root / "baseline" / "fake-model" / "rep0" / "Prob000_fake"
    rec = json.loads((cell_dir / "record.json").read_text())
    assert rec["pass"] is True and rec["harness"] == "baseline" and rec["model"] == "fake-model"
    assert rec["seed"] == Config.load().model.seed and rec["tokens"] == 100
    err = json.loads((root / "baseline" / "fake-model" / "rep0" / "Prob001_fake" / "record.json").read_text())
    assert err["state"] == "error" and "injected cell failure" in err["error"]
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["cells"] == 12 and manifest["spec"]["repeats"] == 2
    assert (root / "progress.log").read_text().count("\n") == 12

    # resume: every cell already has a record.json, so nothing is executed again
    again = run_matrix(spec, resume=str(root), log=lambda m: None, execute=fake_execute)
    assert again["skipped"] == 12 and len(seen) == 12

    board = build_scoreboard(root)
    assert board["records"] == 12
    base = next(g for g in board["groups"] if g["harness"] == "baseline")
    nor = next(g for g in board["groups"] if g["harness"] == "no-review")
    assert base["n"] == 6 and base["pass"] == 2 and base["error"] == 2
    assert base["accepted"] == 2 and base["false_acceptance"] == 0
    assert nor["accepted"] == 4 and nor["false_acceptance"] == 2         # accepted a failing design
    assert nor["fa_rate_among_accepted"] == 0.5
    assert base["stability"] == 1.0 and base["stability_denominator"] == 3
    assert base["tokens_per_pass"] == 200.0   # 400 tokens over 4 non-error cells / 2 passes
    paired = next(p for p in board["paired"] if p["harness"] == "no-review")
    assert paired["paired_problems"] == 3 and paired["delta_pass"] == 0 and paired["mcnemar_p"] == 1.0
    assert (root / "scoreboard.md").is_file()
    assert board["ranking"]["order"][0]["harness"] == "baseline"          # lower false acceptance wins


def test_scoreboard_statistics_against_hand_computed_values():
    lo, hi = wilson(5, 10)
    assert round(lo, 4) == 0.2366 and round(hi, 4) == 0.7634
    assert wilson(0, 0) == (0.0, 1.0)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 0) == 1.0            # 2 * 0.5
    assert mcnemar_exact(5, 0) == 0.0625         # 2 * (1/32)
    assert round(mcnemar_exact(6, 0), 5) == 0.03125
    assert round(mcnemar_exact(8, 2), 4) == 0.1094   # 2 * (C(10,0)+C(10,1)+C(10,2))/2^10
