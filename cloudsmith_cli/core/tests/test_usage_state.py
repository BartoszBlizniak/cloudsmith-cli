import json
import os

from cloudsmith_cli.core.usage import state


def test_read_missing_or_corrupt_is_empty(usage_state_dir):
    assert state.read() == {}
    with open(state.state_path(), "w") as f:
        f.write("{not json")
    assert state.read() == {}


def test_write_merges_and_uses_0600(usage_state_dir):
    assert state.write({"notice_version": 1}) is True
    assert state.write({"last_failure_at": 5.0}) is True
    assert state.read() == {"notice_version": 1, "last_failure_at": 5.0}
    assert oct(os.stat(state.state_path()).st_mode & 0o777) == "0o600"
    with open(state.state_path()) as f:
        assert json.load(f)["notice_version"] == 1


def test_write_failure_returns_false(usage_state_dir, monkeypatch):
    monkeypatch.setattr(state, "state_path", lambda: "/nonexistent/dir/telemetry.json")
    monkeypatch.setattr(
        os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    assert state.write({"x": 1}) is False


def test_writable_true_for_a_writable_dir(usage_state_dir):
    assert state.writable() is True
    assert not os.path.exists(state.state_path())


def test_writable_walks_up_to_the_nearest_existing_dir(usage_state_dir, monkeypatch):
    missing = os.path.join(str(usage_state_dir), "not", "yet")
    monkeypatch.setattr(state, "config_dir", lambda: missing)
    assert state.writable() is True
    assert not os.path.exists(missing)


def test_writable_false_when_not_accessible(usage_state_dir, monkeypatch):
    monkeypatch.setattr(os, "access", lambda *a, **k: False)
    assert state.writable() is False
