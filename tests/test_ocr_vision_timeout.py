import time

import pytest

from core.ocr_vision import OcrTimeoutError, _run_with_soft_timeout


def test_fast_call_returns_normally():
    result = _run_with_soft_timeout(lambda: 42, timeout=5)
    assert result == 42


def test_slow_call_raises_timeout_promptly():
    def slow():
        time.sleep(10)
        return "done"

    t0 = time.time()
    with pytest.raises(OcrTimeoutError):
        _run_with_soft_timeout(slow, timeout=1)
    elapsed = time.time() - t0
    # the CALLER must be released promptly even though the underlying
    # call keeps running in the background (soft timeout, documented
    # limitation -- see ocr_vision.py docstring)
    assert elapsed < 5


def test_exception_from_the_call_itself_propagates():
    def raises():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        _run_with_soft_timeout(raises, timeout=5)
