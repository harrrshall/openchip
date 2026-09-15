"""User-facing summaries derived from recorded run evidence."""
from __future__ import annotations

import difflib
import re
from pathlib import Path


def result_summary(outcome: dict, state: str | None) -> dict:
    questions = [str(q) for q in outcome.get("unresolved", []) if str(q).strip()]
    questions = list(dict.fromkeys(questions))
    provisional = bool(outcome.get("provisional"))
    withheld = "SIGN-OFF WITHHELD" in outcome.get("status_line", "")
    if (provisional or withheld) and not questions:
        questions = ["The independent references disagree or lack corroboration. Please clarify the intended behavior, including timing and priority when inputs coincide."]
    if state in {"running", "planned", "created"}:
        sentence = "Building and checking your design"
    elif questions:
        sentence = f"Needs your answer on {len(questions)} question{'s' if len(questions) != 1 else ''}"
    elif state == "completed" and outcome.get("accepted") and not provisional and not withheld:
        sentence = "Verified and signed off"
    elif state == "budget_exhausted":
        sentence = "Stopped at the time limit; verification is incomplete"
    elif state == "paused":
        sentence = "Paused; verification is incomplete"
    else:
        sentence = "Needs more work before sign-off"
    formal = outcome.get("formal") or {}
    required = (outcome.get("verification_config") or {}).get("require_formal")
    return {"sentence": sentence, "questions": questions,
            "formal": {"status": formal.get("status", "not_run"),
                       "required": required,
                       "informational": required is False}}


def stage_durations(events: list[dict], end: float) -> list[dict]:
    """Checkpoint timestamps mark stage entry; accumulate repeated repair visits."""
    durations: dict[str, float] = {}
    checkpoints = [e for e in events if e.get("kind") == "checkpoint" and e.get("step")]
    for index, event in enumerate(checkpoints):
        stop = checkpoints[index + 1]["ts"] if index + 1 < len(checkpoints) else end
        stage = event["step"]
        durations[stage] = durations.get(stage, 0) + max(0, stop - event["ts"])
    return [{"stage": stage, "seconds": round(seconds, 1)} for stage, seconds in durations.items()]


def contract_diff(spec: list[Path]) -> str:
    if len(spec) < 2:
        return "No previous contract version to compare."
    before, after = spec[-2:]
    return "".join(difflib.unified_diff(before.read_text().splitlines(True),
                                       after.read_text().splitlines(True),
                                       fromfile=before.name, tofile=after.name)) or "No text changes."


def latest_contract(spec_dir: Path) -> dict | None:
    """The newest `contract.v<N>.json` in the spec folder, parsed, or None when there is none or it is unreadable."""
    import json
    import re

    def version(p: Path) -> int:
        m = re.search(r"\.v(\d+)$", p.stem)
        return int(m.group(1)) if m else -1

    files = sorted((p for p in spec_dir.glob("contract.v*.json") if version(p) >= 0), key=version) if spec_dir.is_dir() else []
    for path in reversed(files):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


_INTENT_MAX = 90
_BOILERPLATE = (
    # VerilogEval-style preamble
    r"I\s+would\s+like\s+you\s+to\s+implement\s+a\s+module\s+(?:named|called)\s+`?\w+`?\s+with\s+the\s+following\s+interface\s*\.",
    r"All\s+input\s+and\s+output\s+ports\s+are\s+one\s+bit\s+unless\s+otherwise\s+specified\s*\.",
)
_NAMED_PREFIX = re.compile(
    r"^\s*(?:please\s+)?(?:create|implement|design|write|build|make)\s+(?P<what>.*?)\s*(?:named|called)\s+`?(?P<name>\w+)`?\s*[.:,;]?\s*",
    re.IGNORECASE | re.DOTALL)
_PORT_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:input|output|inout)\b", re.IGNORECASE)
_MODULE_NAMED = re.compile(r"\b(?:module|system)\s+(?:named|called)\s+`?(\w+)`?", re.IGNORECASE)


def _clip(text: str, limit: int = _INTENT_MAX) -> str:
    text = " ".join(text.split()).strip(" .:;,")
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "…"


def _first_sentence(text: str) -> str:
    # a colon at the end of a line or a blank line ends the lead sentence (a list or diagram follows)
    text = re.split(r":[ \t]*\n|\n[ \t]*\n", text.strip(), maxsplit=1)[0]
    text = " ".join(text.split())
    for m in re.finditer(r"[.!?]\s+", text):
        if not re.search(r"\b(?:e\.g|i\.e|etc|vs)\.$", text[: m.start() + 1], re.IGNORECASE):
            return text[: m.start()]
    return text


def request_intent(request: str) -> str:
    """One line of what the request asks for, with the prompt boilerplate stripped."""
    text = (request or "").replace("\r\n", "\n")
    for pattern in _BOILERPLATE:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    lead = ""
    m = _NAMED_PREFIX.match(text)
    if m:
        what = re.sub(r"^(?:an?|the)\s+", "", m.group("what").strip(), flags=re.IGNORECASE)
        what = re.sub(r"\s*\bmodule$", "", what, flags=re.IGNORECASE).strip()
        if what and what.lower() not in {"module", "verilog module", "a module"}:
            lead = what
        text = text[m.end():]
    lines = [ln for ln in text.split("\n") if ln.strip() and not _PORT_LINE.match(ln)
             and not re.match(r"^\s*#", ln)]
    body = _first_sentence("\n".join(lines))
    body = re.sub(r"^the\s+module\s+(?:(?:should|shall|must|will)\s+)?(?:implements?|is|be)\s+", "", body, flags=re.IGNORECASE)
    body = re.sub(r"^(?:an?|the)\s+", "", body, flags=re.IGNORECASE)
    if lead:
        return _clip(lead)
    if body.strip(" .:;,"):
        return _clip(body)
    first = next((ln for ln in (request or "").splitlines() if ln.strip()), "")
    return _clip(first)


def session_identity(contract: dict | None, request: str, workspace: str) -> dict:
    """`module` and `intent` for a session row: the contract first, then the request, then the folder."""
    contract = contract or {}
    module = str(contract.get("module_name") or "").strip()
    if not module:
        m = _MODULE_NAMED.search(request or "")
        module = m.group(1) if m else workspace
    purpose = str(contract.get("purpose") or "").strip()
    intent = _clip(_first_sentence(purpose)) if purpose else request_intent(request)
    return {"module": module, "intent": intent}
