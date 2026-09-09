from openchip.runtime.store import RunStore


def test_checkpoint_resume_and_lock(tmp_path):
    s = RunStore(tmp_path / "runs.db")
    rid = s.create_run(str(tmp_path), "req", {"budget": {}})
    s.checkpoint(rid, "rtl", {"contract_path": "x"})
    s.set_state(rid, "running")
    run = s.get_run(rid)
    assert run["step"] == "rtl" and run["checkpoint"] == {"contract_path": "x"} and run["state"] == "running"
    assert s.acquire_lock(rid, "a")
    assert not s.acquire_lock(rid, "b")
    s.release_lock(rid)
    assert s.acquire_lock(rid, "b")
    kinds = [e["kind"] for e in s.events(rid)]
    assert kinds[:3] == ["run_created", "checkpoint", "state"]
    assert s.latest_run_id() == rid


def test_dead_owner_lock_can_be_taken(tmp_path):
    import socket
    s = RunStore(tmp_path / "runs.db")
    rid = s.create_run(str(tmp_path), "req", {})
    assert s.acquire_lock(rid, f"{socket.gethostname()}:999999")  # pid that does not exist
    assert s.acquire_lock(rid, f"{socket.gethostname()}:1")        # taken over from the dead owner
    assert not s.acquire_lock(rid, "otherhost:1")                  # live-looking owner elsewhere is respected... 
    

def test_stale_lock_can_be_taken(tmp_path):
    s = RunStore(tmp_path / "runs.db")
    rid = s.create_run(str(tmp_path), "req", {})
    assert s.acquire_lock(rid, "dead")
    assert s.acquire_lock(rid, "new", stale_after_s=0.0)
