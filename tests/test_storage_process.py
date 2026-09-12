import subprocess
import sys

import pytest

from a1_stitcher.errors import ProcessError, StitchError
from a1_stitcher.process import binary, read_exact, run, stop, write_all
from a1_stitcher.storage import identity, load_json, output_lock, write_new_json


def test_atomic_json_never_clobbers_regular_file_or_symlink(tmp_path):
    path = tmp_path / "data.json"
    write_new_json(path, {"first": True})
    with pytest.raises(StitchError):
        write_new_json(path, {"second": True})
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(StitchError):
        write_new_json(link, {"second": True})
    assert load_json(path) == {"first": True}
    assert not list(tmp_path.glob(".a1-json-*"))


def test_lock_excludes_competing_writer_and_cleans(tmp_path):
    path = tmp_path / "out.mp4"
    with output_lock(path):
        with pytest.raises(StitchError, match="lock"):
            with output_lock(path):
                pass
    assert not list(tmp_path.iterdir())


def test_lock_does_not_delete_replacement(tmp_path):
    path = tmp_path / "out.mp4"
    lock = tmp_path / "out.mp4.lock"
    with output_lock(path):
        lock.rename(tmp_path / "old-lock")
        lock.write_text("replacement")
    assert lock.read_text() == "replacement"


@pytest.mark.parametrize("text", ['{"x":NaN}', '{"x":Infinity}', "broken"])
def test_strict_json(text, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(text)
    with pytest.raises(StitchError):
        load_json(path)


def test_bounded_json_and_identity_changes(tmp_path):
    path = tmp_path / "value.json"
    path.write_text("{}")
    with pytest.raises(StitchError):
        load_json(path, limit=1)
    old = identity(path)
    path.write_text('{"new":1}')
    assert identity(path) != old


def test_missing_binary_actionable(monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ProcessError, match="not installed"):
        binary("ffmpeg")


def test_nonzero_and_timeout_processes():
    with pytest.raises(ProcessError, match="exited 7"):
        run([sys.executable, "-c", "raise SystemExit(7)"])
    with pytest.raises(ProcessError, match="exceeded"):
        run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.02)


def test_pipe_frame_reads_handle_eof_and_stalls():
    process = subprocess.Popen(
        [sys.executable, "-c", 'import sys;sys.stdout.buffer.write(b"abc")'], stdout=subprocess.PIPE
    )
    try:
        with pytest.raises(ProcessError, match="Incomplete"):
            read_exact(process.stdout, 4, timeout=1)
    finally:
        stop(process)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(5)"], stdout=subprocess.PIPE
    )
    try:
        with pytest.raises(ProcessError, match="Timed out"):
            read_exact(process.stdout, 1, timeout=0.02)
    finally:
        stop(process)


def test_pipe_writer_timeout_is_bounded():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(5)"], stdin=subprocess.PIPE
    )
    try:
        with pytest.raises(ProcessError, match="Timed out"):
            write_all(process.stdin, b"x" * 10_000_000, timeout=0.02)
    finally:
        stop(process)
