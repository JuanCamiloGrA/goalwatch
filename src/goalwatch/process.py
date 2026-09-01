from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Sequence


class ProcessOutputLimitError(subprocess.SubprocessError):
    pass


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def run_bounded(
    command: Sequence[str],
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int = 64 * 1024,
    input_data: bytes | str | None = None,
    text: bool = False,
) -> subprocess.CompletedProcess:
    """Run a process with hard output, wall-clock, and process-group bounds."""
    if stdout_limit < 0 or stderr_limit < 0 or timeout <= 0:
        raise ValueError("Process bounds must be positive.")
    encoded_input = input_data.encode("utf-8") if isinstance(input_data, str) else input_data
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.PIPE if encoded_input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    if encoded_input is not None:
        assert process.stdin is not None
        try:
            process.stdin.write(encoded_input)
            process.stdin.close()
        except BrokenPipeError:
            process.stdin.close()

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, (bytearray(), stdout_limit, "stdout"))
    selector.register(process.stderr, selectors.EVENT_READ, (bytearray(), stderr_limit, "stderr"))
    deadline = time.monotonic() + timeout
    buffers: dict[str, bytearray] = {}
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(command), timeout)
            events = selector.select(remaining)
            if not events:
                raise subprocess.TimeoutExpired(list(command), timeout)
            for key, _mask in events:
                buffer, limit, stream_name = key.data
                chunk = os.read(key.fd, min(64 * 1024, limit - len(buffer) + 1))
                if not chunk:
                    buffers[stream_name] = buffer
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                buffer.extend(chunk)
                if len(buffer) > limit:
                    raise ProcessOutputLimitError(
                        f"Process {stream_name} exceeded its {limit}-byte limit."
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(list(command), timeout)
        returncode = process.wait(timeout=remaining)
    except BaseException:
        _kill_process_group(process)
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass

    stdout = bytes(buffers.get("stdout", b""))
    stderr = bytes(buffers.get("stderr", b""))
    if text:
        return subprocess.CompletedProcess(
            list(command),
            returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    return subprocess.CompletedProcess(list(command), returncode, stdout, stderr)
