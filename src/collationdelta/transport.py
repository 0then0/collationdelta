"""One bounded batch process, with concurrent stdin/stdout/stderr I/O on POSIX."""

import os
import selectors
import signal
import subprocess
import time

from .formats import DeltaError, require


def run(argv, request, *, timeout=30.0, stdout_limit=16 * 1024 * 1024, stderr_limit=1024 * 1024):
    require(os.name == "posix", "adapter execution currently requires Linux or macOS")
    require(
        argv and all(isinstance(arg, str) and arg for arg in argv),
        "adapter argv is empty or invalid",
    )
    require(timeout > 0 and timeout < float("inf"), "timeout must be positive and finite")
    require(stdout_limit > 0 and stderr_limit > 0, "output limits must be positive")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        raise DeltaError(f"adapter launch failed: {exc}") from exc
    output = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    deadline = time.monotonic() + timeout
    offset = 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream, label in (
                (proc.stdin, "stdin"),
                (proc.stdout, "stdout"),
                (proc.stderr, "stderr"),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(
                    stream,
                    selectors.EVENT_WRITE if label == "stdin" else selectors.EVENT_READ,
                    label,
                )
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DeltaError(f"adapter timeout after {timeout:g}s")
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream, label = key.fileobj, key.data
                    if label == "stdin":
                        try:
                            offset += os.write(stream.fileno(), request[offset : offset + 65536])
                        except BrokenPipeError:
                            offset = len(request)
                        if offset == len(request):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                        else:
                            if len(output[label]) + len(chunk) > limits[label]:
                                raise DeltaError(
                                    f"adapter {label} exceeds {limits[label]} byte limit"
                                )
                            output[label].extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeltaError(f"adapter timeout after {timeout:g}s")
            try:
                code = proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise DeltaError(f"adapter timeout after {timeout:g}s") from exc
            if code != 0:
                diagnostic = bytes(output["stderr"]).decode("utf-8", errors="replace")
                raise DeltaError(f"adapter exited {code}; stderr={diagnostic!r}")
            return bytes(output["stdout"]), bytes(output["stderr"])
    finally:
        # Also close descendant-held pipes and stop descendants on timeout/limits.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()
