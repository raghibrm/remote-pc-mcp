import subprocess

import pytest

from remote_pc_mcp import daemon


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point the daemon's log and lock at tmp, make sleeps instant, and record
    server launches instead of running them. Each launch exits cleanly, which
    stops the daemon, so main() returns after the first one."""
    monkeypatch.setattr(daemon, "_LOG_FILE", tmp_path / "daemon.log")
    monkeypatch.setattr(daemon, "_LOCK_FILE", tmp_path / ".state" / "daemon.lock")
    monkeypatch.setattr(daemon.time, "sleep", lambda s: None)
    launches = []

    def fake_run(cmd, env=None):
        launches.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    yield launches
    logger = daemon.logging.getLogger("remote-pc-mcp.daemon")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _health(monkeypatch, answers):
    """Answer health checks from a list, then fail the test if asked again."""
    answers = list(answers)

    def fake_up():
        assert answers, "health checked more often than expected"
        return answers.pop(0)

    monkeypatch.setattr(daemon, "_server_already_up", fake_up)
    return answers


def test_starts_a_server_when_none_is_running(isolated, monkeypatch):
    _health(monkeypatch, [False])
    assert daemon.main() == 0
    assert len(isolated) == 1


def test_watches_a_running_server_and_takes_over_when_it_stops(isolated, monkeypatch):
    remaining = _health(monkeypatch, [True, True, True, False, False, False])
    assert daemon.main() == 0
    assert len(isolated) == 1
    assert remaining == []


def test_only_consecutive_misses_trigger_a_takeover(isolated, monkeypatch):
    # Two misses, a recovery, then three misses in a row.
    remaining = _health(monkeypatch, [True, False, False, True, False, False, False])
    assert daemon.main() == 0
    assert len(isolated) == 1
    assert remaining == []


def test_second_daemon_leaves_while_the_first_holds_the_lock(isolated, monkeypatch):
    _health(monkeypatch, [])  # the second daemon must not even check health
    first = daemon._acquire_lock()
    assert first is not None
    try:
        assert daemon.main() == 0
        assert isolated == []
    finally:
        first.close()


def test_lock_is_free_again_after_its_holder_closes(isolated):
    first = daemon._acquire_lock()
    first.close()
    second = daemon._acquire_lock()
    assert second is not None
    second.close()
