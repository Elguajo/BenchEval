import pytest

from bencheval.contracts import ExecutionStatus
from bencheval.executors.codex import CodexExecutor, provider_lock
from bencheval.runtime import ProcessResult


@pytest.mark.parametrize(
    "cancelled,status",
    [
        (False, ExecutionStatus.TIMEOUT),
        (True, ExecutionStatus.CANCELLED),
    ],
)
def test_preflight_failure_is_not_auth_failure(
    scenario, tmp_path, monkeypatch, cancelled, status
):
    import bencheval.executors.codex as codex

    monkeypatch.setattr(codex.shutil, "which", lambda _: "/fake/codex")
    monkeypatch.setattr(
        codex,
        "run_process",
        lambda *args, **kwargs: ProcessResult(
            "", "", -1, 0.1, timed_out=not cancelled, cancelled=cancelled
        ),
    )
    execution = CodexExecutor().run(scenario, "Return 4.", tmp_path)
    assert execution.status == status


def test_provider_lock_releases_after_failure():
    with provider_lock():
        with pytest.raises(OSError, match="already running"):
            with provider_lock():
                pytest.fail("Second provider invocation acquired the lock")
    with provider_lock():
        pass
