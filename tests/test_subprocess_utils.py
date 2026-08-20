import subprocess
import time

import pytest

from core.subprocess_utils import SubprocessTimeoutError, run_subprocess


def test_fast_command_returns_normally():
    result = run_subprocess(["echo", "hello"], timeout=5, capture_output=True, text=True)
    assert result.stdout.strip() == "hello"


def test_slow_command_raises_timeout_error_promptly():
    t0 = time.time()
    with pytest.raises(SubprocessTimeoutError):
        run_subprocess(["sleep", "10"], timeout=1)
    elapsed = time.time() - t0
    # must not silently hang past the requested timeout
    assert elapsed < 5


def test_timeout_error_message_names_the_command():
    with pytest.raises(SubprocessTimeoutError) as exc_info:
        run_subprocess(["sleep", "10"], timeout=1)
    assert "sleep" in str(exc_info.value)


def test_child_process_is_actually_killed_not_orphaned():
    # a command that would write a marker file only if it runs to
    # completion -- if the timeout truly kills it, the marker never
    # appears, even after waiting past the child's original sleep duration
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "marker.txt"
        with pytest.raises(SubprocessTimeoutError):
            run_subprocess(
                ["sh", "-c", f"sleep 5 && touch {marker}"], timeout=1
            )
        time.sleep(5.5)  # past when the child WOULD have finished if not killed
        assert not marker.exists()


def test_non_timeout_failure_still_raises_called_process_error():
    with pytest.raises(subprocess.CalledProcessError):
        run_subprocess(["false"], timeout=5, check=True)


def test_default_timeout_is_used_when_not_specified():
    # just confirms calling without an explicit timeout doesn't crash --
    # a real hang-forever call is exercised by the explicit-timeout tests
    result = run_subprocess(["echo", "ok"], capture_output=True, text=True)
    assert result.stdout.strip() == "ok"
