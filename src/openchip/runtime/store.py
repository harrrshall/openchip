"""SQLite-backed run store: transactional state plus an append-only event log.

Enough is persisted after each meaningful action to resume without private model reasoning.
"""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

STATES = ("created", "needs_input", "planned", "running", "paused", "completed", "failed", "stalled", "budget_exhausted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
  project_dir TEXT NOT NULL, request TEXT NOT NULL, config_json TEXT NOT NULL,
  step TEXT NOT NULL DEFAULT 'intake', checkpoint_json TEXT NOT NULL DEFAULT '{}', outcome_json TEXT NOT NULL DEFAULT '{}',
  lock_owner TEXT DEFAULT '', lock_ts REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, step TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ev_run ON events(run_id, id);
"""


def lock_owner_id() -> str:
    import os
    import socket
    return f"{socket.gethostname()}:{os.getpid()}"


def _owner_alive(owner: str) -> bool:
    """True if the lock owner is a live process on this host; unknown hosts are assumed alive."""
    import os
    import socket
    host, _, pid = owner.rpartition(":")
    if host != socket.gethostname() or not pid.isdigit():
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One store is used by one logical run at a time; the UI hands a store from its HTTP thread to the
        # worker thread, so the same-thread check is disabled (SQLite itself serialises access).
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # -- runs -----------------------------------------------------------------------------
    def create_run(self, project_dir: str, request: str, config: dict) -> str:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        now = time.time()
        self.db.execute("INSERT INTO runs(run_id,state,created,updated,project_dir,request,config_json) VALUES (?,?,?,?,?,?,?)",
                        (run_id, "created", now, now, project_dir, request, json.dumps(config)))
        self.event(run_id, "run_created", {"project_dir": project_dir})
        return run_id

    def get_run(self, run_id: str) -> Optional[dict]:
        cur = self.db.execute("SELECT run_id,state,created,updated,project_dir,request,config_json,step,checkpoint_json,outcome_json,lock_owner,lock_ts FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        keys = ["run_id", "state", "created", "updated", "project_dir", "request", "config", "step", "checkpoint", "outcome", "lock_owner", "lock_ts"]
        d = dict(zip(keys, row))
        d["config"] = json.loads(d["config"])
        d["checkpoint"] = json.loads(d["checkpoint"])
        d["outcome"] = json.loads(d["outcome"])
        return d

    def list_runs(self) -> list[dict]:
        cur = self.db.execute("SELECT run_id,state,created,updated,step FROM runs ORDER BY created DESC")
        return [dict(zip(["run_id", "state", "created", "updated", "step"], r)) for r in cur.fetchall()]

    def latest_run_id(self) -> Optional[str]:
        runs = self.list_runs()
        return runs[0]["run_id"] if runs else None

    def set_state(self, run_id: str, state: str, **payload: Any) -> None:
        assert state in STATES, state
        self.db.execute("UPDATE runs SET state=?, updated=? WHERE run_id=?", (state, time.time(), run_id))
        self.event(run_id, "state", {"state": state, **payload})

    def checkpoint(self, run_id: str, step: str, data: dict) -> None:
        """Transactionally record the step reached and the data needed to resume after it."""
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("UPDATE runs SET step=?, checkpoint_json=?, updated=? WHERE run_id=?", (step, json.dumps(data), time.time(), run_id))
            self.db.execute("INSERT INTO events(run_id,ts,kind,payload_json) VALUES (?,?,?,?)", (run_id, time.time(), "checkpoint", json.dumps({"step": step})))

    def set_outcome(self, run_id: str, outcome: dict) -> None:
        self.db.execute("UPDATE runs SET outcome_json=?, updated=? WHERE run_id=?", (json.dumps(outcome), time.time(), run_id))

    # -- locks ------------------------------------------------------------------------------
    def acquire_lock(self, run_id: str, owner: str, stale_after_s: float = 900.0) -> bool:
        """Owner format is 'host:pid'. A lock is free if unowned, ours, stale, or held by a process that no
        longer exists on this host (e.g. after SIGKILL or a host restart)."""
        row = self.db.execute("SELECT lock_owner, lock_ts FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row and row[0] and row[0] != owner and time.time() - row[1] < stale_after_s and _owner_alive(row[0]):
            return False
        self.db.execute("UPDATE runs SET lock_owner=?, lock_ts=? WHERE run_id=?", (owner, time.time(), run_id))
        return True

    def lock_is_live(self, run_id: str) -> bool:
        row = self.db.execute("SELECT lock_owner FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return bool(row and row[0] and _owner_alive(row[0]))

    def touch_lock(self, run_id: str) -> None:
        self.db.execute("UPDATE runs SET lock_ts=? WHERE run_id=?", (time.time(), run_id))

    def release_lock(self, run_id: str) -> None:
        self.db.execute("UPDATE runs SET lock_owner='', lock_ts=0 WHERE run_id=?", (run_id,))

    # -- events / artifacts -------------------------------------------------------------------
    def event(self, run_id: str, kind: str, payload: dict) -> None:
        self.db.execute("INSERT INTO events(run_id,ts,kind,payload_json) VALUES (?,?,?,?)", (run_id, time.time(), kind, json.dumps(payload, default=str)))

    def events(self, run_id: str, kind: Optional[str] = None) -> list[dict]:
        if kind:
            cur = self.db.execute("SELECT ts,kind,payload_json FROM events WHERE run_id=? AND kind=? ORDER BY id", (run_id, kind))
        else:
            cur = self.db.execute("SELECT ts,kind,payload_json FROM events WHERE run_id=? ORDER BY id", (run_id,))
        events = []
        for ts, event_kind, raw in cur.fetchall():
            payload = json.loads(raw)
            # Domain evidence may itself have a kind (for example a clock check).
            # It must not replace the persisted event identity used by history/resume.
            if "kind" in payload:
                payload["payload_kind"] = payload["kind"]
            events.append({**payload, "ts": ts, "kind": event_kind})
        return events

    def artifact(self, run_id: str, name: str, path: Path, step: str) -> str:
        saved = self.retain(path)
        h = hashlib.sha256(saved.read_bytes()).hexdigest()
        self.db.execute("INSERT INTO artifacts(run_id,ts,name,path,sha256,step) VALUES (?,?,?,?,?,?)", (run_id, time.time(), name, str(saved), h, step))
        return h

    def retain(self, path: Path, expected_sha256: str | None = None) -> Path:
        """Retain exact workspace bytes without overwriting an existing object."""
        root = self.path.resolve().parent.parent
        source = Path(path).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError("Artifact must be a regular file inside the workspace")
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 and digest != expected_sha256:
            raise ValueError("Artifact no longer matches its recorded hash")
        target = root / "retained" / "artifacts" / digest / source.name
        if not target.resolve().is_relative_to(root):
            raise ValueError("Retained artifact destination escapes the workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        # A temporary file plus a hard link publishes complete bytes atomically,
        # without replacing another writer's object at the same content hash.
        temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o444)
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != data:
                    raise ValueError("Retained artifact is corrupt; refusing to replace it")
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def retain_before_revision(self, run_id: str) -> None:
        """Migrate matching legacy links before canonical files are regenerated.

        Missing or previously changed bytes are recorded as unavailable; their
        expected hashes are never replaced with hashes of a newer design.
        """
        run = self.get_run(run_id)
        if not run:
            return
        original_outcome = self.db.execute("SELECT outcome_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
        outcome = run["outcome"]
        mapping, unavailable, legacy_unhashed = {}, [], []
        for ident, name, path, digest in self.db.execute(
                "SELECT id,name,path,sha256 FROM artifacts WHERE run_id=?", (run_id,)).fetchall():
            try:
                saved = self.retain(Path(path), digest)
                mapping[path] = str(saved)
                self.db.execute("UPDATE artifacts SET path=? WHERE id=?", (str(saved), ident))
            except (OSError, ValueError) as exc:
                unavailable.append({"name": name, "path": path, "error": str(exc)})
        artifacts = outcome.get("artifacts", {})
        for name in ("contract", "rtl", "reference", "properties"):
            path, digest = artifacts.get(name), artifacts.get(name + "_sha256")
            if path and digest:
                try:
                    saved = self.retain(Path(path), digest)
                    mapping[path] = str(saved)
                    artifacts[name] = str(saved)
                except (OSError, ValueError) as exc:
                    unavailable.append({"name": name, "path": path, "error": str(exc)})
        for reference in (outcome.get("reference_consensus") or {}).get("references", []):
            path = reference.get("path")
            if not path:
                continue
            try:
                saved = self.retain(Path(path), reference.get("sha256"))
                if not reference.get("sha256"):
                    legacy_unhashed.append(path)
                mapping[path] = str(saved)
                reference.update(path=str(saved), sha256=hashlib.sha256(saved.read_bytes()).hexdigest())
            except (OSError, ValueError) as exc:
                unavailable.append({"name": "consensus_reference", "path": path, "error": str(exc)})
        # Keep the original outcome alongside the migrated index.
        archive = self.path.resolve().parent.parent / "retained" / "revisions" / uuid.uuid4().hex
        if not archive.resolve().is_relative_to(self.path.resolve().parent.parent):
            raise ValueError("Retention destination escapes the workspace")
        archive.mkdir(parents=True)
        (archive / "outcome-before-retention.json").write_text(original_outcome)
        (archive / "outcome.json").write_text(json.dumps(outcome, indent=2))
        self.db.execute("UPDATE runs SET outcome_json=? WHERE run_id=?", (json.dumps(outcome), run_id))
        self.event(run_id, "artifacts_retained_before_revision", {
            "paths": mapping, "unavailable": unavailable, "legacy_sources_without_prior_hash": legacy_unhashed,
            "outcome": str(archive / "outcome.json")})

    def artifacts(self, run_id: str) -> list[dict]:
        cur = self.db.execute("SELECT ts,name,path,sha256,step FROM artifacts WHERE run_id=? ORDER BY id", (run_id,))
        return [dict(zip(["ts", "name", "path", "sha256", "step"], r)) for r in cur.fetchall()]

    def close(self) -> None:
        self.db.close()
