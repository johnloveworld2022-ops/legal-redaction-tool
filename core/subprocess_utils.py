import subprocess

# A corrupted or pathological input file (a malformed PDF, an oversized
# scan) can make pdftoppm/pdftotext/textutil/pdfimages hang indefinitely.
# Every external command in this tool goes through here so none of them
# can wedge the GUI forever -- subprocess.run's own timeout mechanism
# already kills the child process on expiry (verified: a killed child
# never reaches code that would prove it kept running), this wrapper only
# gives callers one specific exception type to catch instead of every
# possible subprocess failure mode.
DEFAULT_TIMEOUT_SECONDS = 60


class SubprocessTimeoutError(RuntimeError):
    def __init__(self, args: list, timeout: float):
        self.args_list = args
        self.timeout = timeout
        command = " ".join(str(a) for a in args)
        super().__init__(f"外部命令超时({timeout}秒): {command}")


def run_subprocess(
    args: list, timeout: float = DEFAULT_TIMEOUT_SECONDS, **kwargs
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as e:
        raise SubprocessTimeoutError(args, timeout) from e
