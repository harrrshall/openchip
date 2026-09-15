"""Aggregate a harness matrix into a scoreboard: reliability first, then efficiency.

    openchip matrix report <matrix-root>     ->  <root>/scoreboard.md, <root>/scoreboard.json

Reliability is what this project is judged by, so the main table leads with false acceptance
(the agent accepted a design the independent check fails) rather than pass rate. Every rate
carries its denominator and a Wilson 95% interval; a difference against `baseline` on the same
model is reported as paired discordant counts with an exact (binomial) McNemar p-value, because
run-to-run noise on this benchmark is several problems wide.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Optional

Z95 = 1.959963984540054


# ------------------------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. (0.0, 1.0) when n == 0."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact (binomial) McNemar p-value for discordant pairs b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2 * tail)


def _rate(k: int, n: int) -> Optional[float]:
    return round(k / n, 4) if n else None


# ------------------------------------------------------------------------------- loading
def load_records(root: str | Path) -> list[dict]:
    recs = []
    for p in sorted(Path(root).rglob("record.json")):
        try:
            recs.append(json.loads(p.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return recs


def _majority_pass(reps: list[dict]) -> Optional[bool]:
    """Outcome for one problem across repeats: majority, ties broken by the first repeat."""
    if not reps:
        return None
    reps = sorted(reps, key=lambda r: r.get("rep", 0))
    votes = [bool(r.get("pass")) for r in reps]
    if votes.count(True) * 2 == len(votes):
        return votes[0]
    return votes.count(True) * 2 > len(votes)


# ------------------------------------------------------------------------------- aggregation
def summarize_group(recs: list[dict]) -> dict:
    n = len(recs)
    npass = sum(bool(r.get("pass")) for r in recs)
    accepted = [r for r in recs if r.get("accepted")]
    fa = sum(bool(r.get("false_acceptance")) for r in recs)
    walls = [float(r.get("wall_s") or 0.0) for r in recs]
    tokens = sum(int(r.get("tokens") or 0) for r in recs)
    # withheld: the pipeline ran, produced RTL, and declined to accept it
    withheld = sum(1 for r in recs if not r.get("accepted")
                   and r.get("status") in ("pass", "fail", "no_consensus"))
    by_problem: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        by_problem[r.get("problem", "?")].append(r)
    repeated = [v for v in by_problem.values() if len(v) > 1]
    stable = sum(1 for v in repeated if len({bool(r.get("pass")) for r in v}) == 1)
    return {
        "n": n, "problems": len(by_problem), "pass": npass, "pass_rate": _rate(npass, n),
        "pass_ci95": [round(x, 4) for x in wilson(npass, n)],
        "accepted": len(accepted), "false_acceptance": fa,
        "fa_rate_among_accepted": _rate(fa, len(accepted)),
        "fa_ci95_among_accepted": [round(x, 4) for x in wilson(fa, len(accepted))],
        "withheld": withheld, "provisional": sum(bool(r.get("provisional")) for r in recs),
        "no_rtl": sum(r.get("status") == "no_rtl" for r in recs),
        "error": sum(r.get("state") == "error" for r in recs),
        "states": {s: sum(r.get("state") == s for r in recs) for s in sorted({r.get("state") for r in recs} - {None})},
        "mean_wall_s": round(statistics.fmean(walls), 1) if walls else 0.0,
        "median_wall_s": round(statistics.median(walls), 1) if walls else 0.0,
        "model_calls": sum(int(r.get("model_calls") or 0) for r in recs),
        "tokens": tokens, "tool_time_s": round(sum(float(r.get("tool_time_s") or 0.0) for r in recs), 1),
        "stability": _rate(stable, len(repeated)),
        "stability_denominator": len(repeated),
        "tokens_per_pass": round(tokens / npass, 1) if npass else None,
        "wall_s_per_pass": round(sum(walls) / npass, 1) if npass else None,
    }


def paired_vs_baseline(records: list[dict], baseline: str = "baseline") -> list[dict]:
    """Per model, compare every harness against `baseline` problem by problem."""
    by: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in records:
        by[(r.get("model", "?"), r.get("harness", "?"), r.get("problem", "?"))].append(r)
    models = sorted({k[0] for k in by})
    harnesses = sorted({k[1] for k in by})
    rows = []
    for model in models:
        for h in harnesses:
            if h == baseline:
                continue
            both = b_only = c_only = concordant_pass = concordant_fail = 0
            for problem in sorted({k[2] for k in by if k[0] == model}):
                base = _majority_pass(by.get((model, baseline, problem), []))
                var = _majority_pass(by.get((model, h, problem), []))
                if base is None or var is None:
                    continue
                both += 1
                if base and not var:
                    b_only += 1
                elif var and not base:
                    c_only += 1
                elif base and var:
                    concordant_pass += 1
                else:
                    concordant_fail += 1
            if not both:
                continue
            rows.append({"model": model, "harness": h, "paired_problems": both,
                         "baseline_only_pass": b_only, "harness_only_pass": c_only,
                         "both_pass": concordant_pass, "both_fail": concordant_fail,
                         "delta_pass": c_only - b_only,
                         "mcnemar_p": round(mcnemar_exact(b_only, c_only), 4)})
    return rows


def rank(groups: list[dict]) -> dict:
    """Order by false acceptance ascending, pass descending, tokens per pass ascending."""
    ordered = sorted(groups, key=lambda g: (
        g["fa_rate_among_accepted"] if g["fa_rate_among_accepted"] is not None else 1.0,
        -(g["pass_rate"] or 0.0),
        g["tokens_per_pass"] if g["tokens_per_pass"] is not None else float("inf")))
    flag = None
    if len(ordered) >= 2:
        a, b = ordered[0]["pass_ci95"], ordered[1]["pass_ci95"]
        if a[0] <= b[1] and b[0] <= a[1]:
            flag = (f"pass-rate 95% intervals of the top two overlap "
                    f"({ordered[0]['harness']}/{ordered[0]['model']} {a} vs "
                    f"{ordered[1]['harness']}/{ordered[1]['model']} {b}): the order is not separated by this data")
    return {"order": [{"harness": g["harness"], "model": g["model"],
                       "fa_rate_among_accepted": g["fa_rate_among_accepted"],
                       "pass_rate": g["pass_rate"], "tokens_per_pass": g["tokens_per_pass"]} for g in ordered],
            "ci_overlap_warning": flag}


def build_scoreboard(root: str | Path, baseline: str = "baseline", write: bool = True) -> dict:
    root = Path(root)
    records = load_records(root)
    if not records:
        return {"root": str(root), "records": 0, "groups": [], "paired": [], "ranking": {}}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        grouped[(r.get("harness", "?"), r.get("model", "?"))].append(r)
    groups = []
    for (h, m), recs in sorted(grouped.items()):
        g = {"harness": h, "model": m, "mode": recs[0].get("mode", "agent")}
        g.update(summarize_group(recs))
        groups.append(g)
    board = {"root": str(root), "records": len(records), "baseline": baseline,
             "groups": groups, "paired": paired_vs_baseline(records, baseline),
             "ranking": rank(groups)}
    if write:
        (root / "scoreboard.json").write_text(json.dumps(board, indent=1))
        (root / "scoreboard.md").write_text(render_markdown(board))
    return board


# ------------------------------------------------------------------------------- rendering
def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def _ci(ci: list[float]) -> str:
    return f"[{ci[0] * 100:.0f}, {ci[1] * 100:.0f}]"


def render_markdown(board: dict) -> str:
    out = [f"# Harness matrix scoreboard — `{board['root']}`", "",
           f"{board['records']} cells. Reliability first: false acceptance = the pipeline accepted a design "
           "the independent check fails. Intervals are Wilson 95%. Paired comparisons are against "
           f"`{board['baseline']}` on the same model, problem by problem (majority across repeats), with an "
           "exact binomial McNemar p-value.", "",
           "| harness | model | n | pass | pass rate (95% CI) | accepted | false acc. | FA rate among accepted (95% CI) | withheld | prov. | no_rtl | error | stability | mean/median wall s | tokens | tokens/pass |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in board["groups"]:
        out.append(
            f"| {g['harness']} | {g['model']} | {g['n']} | {g['pass']} | {_pct(g['pass_rate'])} {_ci(g['pass_ci95'])} "
            f"| {g['accepted']} | {g['false_acceptance']} | {_pct(g['fa_rate_among_accepted'])} {_ci(g['fa_ci95_among_accepted'])} "
            f"| {g['withheld']} | {g['provisional']} | {g['no_rtl']} | {g['error']} "
            f"| {_pct(g['stability'])} (n={g['stability_denominator']}) | {g['mean_wall_s']}/{g['median_wall_s']} "
            f"| {g['tokens']} | {g['tokens_per_pass'] if g['tokens_per_pass'] is not None else '-'} |")
    out += ["", f"## Paired against `{board['baseline']}` (same model, same problem)", "",
            "| model | harness | paired problems | both pass | both fail | baseline only | harness only | delta | McNemar p (exact) |",
            "|---|---|---|---|---|---|---|---|---|"]
    for p in board["paired"]:
        out.append(f"| {p['model']} | {p['harness']} | {p['paired_problems']} | {p['both_pass']} | {p['both_fail']} "
                   f"| {p['baseline_only_pass']} | {p['harness_only_pass']} | {p['delta_pass']:+d} | {p['mcnemar_p']} |")
    if not board["paired"]:
        out.append("| (no paired cells) | | | | | | | | |")
    rk = board["ranking"]
    out += ["", "## Ranking (false acceptance asc, pass desc, tokens per pass asc)", ""]
    out += [f"{i + 1}. `{e['harness']}` / `{e['model']}` — FA {_pct(e['fa_rate_among_accepted'])}, "
            f"pass {_pct(e['pass_rate'])}, {e['tokens_per_pass'] if e['tokens_per_pass'] is not None else '-'} tokens/pass"
            for i, e in enumerate(rk.get("order", []))]
    if rk.get("ci_overlap_warning"):
        out += ["", f"**Caution:** {rk['ci_overlap_warning']}."]
    return "\n".join(out) + "\n"
