"""No-clobber publication, bounded configuration, and reproducible identities."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import StitchError


def json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False, sort_keys=True) + "\n").encode()


def load_json(path, limit=16 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise StitchError("JSON input exceeds the configured size limit")
    try:
        return json.loads(
            path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
        )
    except (ValueError, UnicodeError) as exc:
        raise StitchError(f"Invalid JSON in {path.name}: {exc}") from exc


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    if not path.is_file():
        raise StitchError("Source must be a regular file")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        h.update(stream.read(1024 * 1024))
        stream.seek(max(0, stat.st_size - 1024 * 1024))
        h.update(stream.read(1024 * 1024))
    return dict(
        method="stat-and-edge-sha256-v1",
        bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        device=stat.st_dev,
        inode=stat.st_ino,
        edge_sha256=h.hexdigest(),
    )


def fingerprint(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def publish_file(staged, output):
    """Same-filesystem hard link is atomic and refuses existing files/symlinks."""
    try:
        os.link(staged, output)
    except FileExistsError as exc:
        raise StitchError(f"Output already exists: {output}") from exc


def write_new_json(output, value):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".a1-json-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        publish_file(staged, output)
    finally:
        Path(staged).unlink(missing_ok=True)


@contextmanager
def output_lock(output):
    path = Path(str(output) + ".lock")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise StitchError(
            f"Job lock exists: {path}. Check the owning process before removing it."
        ) from exc
    owned = os.fstat(fd)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"pid": os.getpid(), "output": str(output)}, stream)
        yield
    finally:
        try:
            current = path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                path.unlink()
        except FileNotFoundError:
            pass
