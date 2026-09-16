"""Compare the current workspace with the artifacts a recorded run signed off.

Historical reports stay immutable. Read-time views can withhold their acceptance
for changed files without rewriting the result of the original run.
"""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Mapping


def workspace_outcome(root: Path, outcome: dict, contents: Mapping[str, bytes] | None = None) -> dict:
    view = copy.deepcopy(outcome)
    if not outcome.get("accepted"):
        return view
    artifacts = outcome.get("artifacts") or {}
    checks = []
    for kind, folder in [("rtl", "rtl"), ("reference", "reference"), ("contract", "spec"), ("properties", "verification")]:
        recorded = artifacts.get(kind)
        if kind == "properties" and not recorded:
            continue
        expected = artifacts.get(kind + "_sha256", "")
        name = Path(str(recorded or "")).name
        relative = f"{folder}/{name}" if name else ""
        actual = ""
        status = "unverifiable"
        if name and re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            try:
                if contents is not None:
                    data = contents[relative]
                else:
                    path = root / relative
                    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError("artifact escapes workspace")
                    data = path.read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                status = "matched" if actual == expected else "changed"
            except (OSError, KeyError, ValueError):
                status = "missing"
        checks.append({"kind": kind, "path": relative, "status": status,
                       "recorded_sha256": expected, "current_sha256": actual})
    known_rtl = {item["path"] for item in checks if item["kind"] == "rtl"}
    rtl_files = (contents.keys() if contents is not None else
                 (str(p.relative_to(root)) for p in (root / "rtl").rglob("*") if p.is_file() or p.is_symlink()))
    for relative in sorted(rtl_files):
        if relative.startswith("rtl/") and Path(relative).suffix in {".v", ".sv"} and relative not in known_rtl:
            checks.append({"kind": "rtl", "path": relative, "status": "unrecorded",
                           "recorded_sha256": "", "current_sha256": ""})
    changed = [item for item in checks if item["status"] != "matched"]
    view["artifact_integrity"] = {"status": "changed" if changed else "matched", "checks": checks}
    if changed:
        view["recorded_accepted"] = True
        view["accepted"] = False
        message = "Current files differ from the recorded run; its sign-off does not apply. Review the changed files and verification evidence. Retained originals and historical reports are unchanged."
        view["artifact_integrity"]["message"] = message
        view["status_line"] = view.get("status_line", "") + "; SIGN-OFF WITHHELD: " + message
    return view


def integrity_warning(outcome: dict) -> str:
    integrity = outcome.get("artifact_integrity") or {}
    if integrity.get("status") != "changed":
        return ""
    return "> CURRENT WORKSPACE: " + integrity["message"] + "\n\n"
