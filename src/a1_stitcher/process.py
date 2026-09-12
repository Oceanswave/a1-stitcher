"""Bounded FFmpeg calls and deadline-aware pipe reads on macOS/Linux."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time

from .errors import ProcessError


def binary(name):
    path = shutil.which(name)
    if path is None:
        raise ProcessError(f"{name} is not installed or not on PATH")
    return path


def run(args, timeout=120):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(f"{os.path.basename(str(args[0]))} exceeded {timeout}s") from exc
    except OSError as exc:
        raise ProcessError(str(exc)) from exc
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace")[-4000:]
        raise ProcessError(f"{os.path.basename(str(args[0]))} exited {result.returncode}: {error}")
    return result.stdout


def probe(path):
    try:
        return json.loads(
            run(
                [
                    binary("ffprobe"),
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ]
            )
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProcessError("ffprobe returned invalid JSON") from exc


def read_exact(stream, size, timeout=120):
    deadline = time.monotonic() + timeout
    data = bytearray(size)
    view = memoryview(data)
    offset = 0
    while offset < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
            raise ProcessError("Timed out waiting for a decoded frame")
        chunk = os.read(stream.fileno(), min(size - offset, 1024 * 1024))
        if not chunk:
            raise ProcessError(f"Incomplete decoded frame: {offset}/{size} bytes")
        view[offset : offset + len(chunk)] = chunk
        offset += len(chunk)
    return data


def write_all(stream, data, timeout=120):
    os.set_blocking(stream.fileno(), False)
    deadline = time.monotonic() + timeout
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([], [stream], [], remaining)[1]:
            raise ProcessError("Timed out writing a video frame")
        try:
            offset += os.write(stream.fileno(), view[offset : offset + 65536])
        except BlockingIOError:
            continue
        except BrokenPipeError as exc:
            raise ProcessError("Video encoder closed its input unexpectedly") from exc


def stop(process):
    if process.poll() is None:
        process.kill()
    process.wait()
    for stream in [process.stdin, process.stdout, process.stderr]:
        if stream is not None:
            stream.close()
