"""Customer design workspace layout, kept separate from the OpenChip source tree."""
from __future__ import annotations

import json
from pathlib import Path

SUBDIRS = ("request", "spec", "reference", "rtl", "verification", "reports", ".openchip")
MANIFEST = ".openchip/manifest.json"


def contract_files(spec: Path) -> list[Path]:
    """Contract snapshots in numeric revision order, oldest first."""
    return sorted(spec.glob("contract.v*.json"), key=lambda path: int(path.stem.split(".v")[1]))


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST

    @property
    def db_path(self) -> Path:
        return self.root / ".openchip" / "runs.db"

    def exists(self) -> bool:
        return self.manifest_path.is_file()

    def init(self, request: str | None = None, name: str | None = None) -> None:
        if self.root.exists() and not self.exists():
            # Never take over an unrelated non-empty directory silently.
            foreign = [p.name for p in self.root.iterdir() if p.name not in SUBDIRS and not p.name.startswith(".")]
            if foreign:
                raise FileExistsError(f"{self.root} is a non-empty directory that is not an OpenChip workspace: {foreign[:5]}")
        for d in SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not self.exists():
            self.manifest_path.write_text(json.dumps({"openchip_workspace": 1, "name": name or self.root.name, "layout": {d: d for d in SUBDIRS}}, indent=1))
        if request is not None:
            (self.root / "request" / "request.md").write_text(request.strip() + "\n")

    def request_text(self) -> str:
        p = self.root / "request" / "request.md"
        return p.read_text() if p.is_file() else ""

    def manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text()) if self.exists() else {}

    def dir(self, name: str) -> Path:
        p = self.root / self.manifest().get("layout", {}).get(name, name)
        p.mkdir(parents=True, exist_ok=True)
        return p
