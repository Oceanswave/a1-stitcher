"""Add monoscopic equirectangular V2 metadata to an owned, moov-last MP4.

Specification: google/spatial-media/docs/spherical-video-v2-rfc.md.
Tagging preserves media offsets; fast-start relocation adjusts chunk offsets.
Unsupported layouts fail closed.
"""

import struct


def box(kind, body):
    return struct.pack(">I4s", len(body) + 8, kind) + body


def children(data, start=0):
    pos = start
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("Truncated MP4 box")
        size, kind = struct.unpack_from(">I4s", data, pos)
        if size < 8 or pos + size > len(data):
            raise ValueError("Unsupported or invalid MP4 box size")
        yield kind, data[pos + 8 : pos + size]
        pos += size


def spherical_boxes():
    stereo = box(b"st3d", bytes(5))
    header = box(b"svhd", bytes(4) + b"A1 experimental local converter\0")
    projection = box(b"proj", box(b"prhd", bytes(16)) + box(b"equi", bytes(20)))
    return stereo + box(b"sv3d", header + projection)


def inject_moov(data):
    count = 0

    def visit(kind, payload):
        nonlocal count
        if kind in [b"moov", b"trak", b"mdia", b"minf", b"stbl"]:
            return box(kind, b"".join(visit(k, p) for k, p in children(payload)))
        if kind == b"stsd":
            entries = []
            for entry_kind, entry in children(payload, 8):
                if entry_kind in [b"avc1", b"hvc1", b"hev1", b"apch", b"apcn"]:
                    if len(entry) < 78:
                        raise ValueError("Invalid video sample entry")
                    existing = list(children(entry, 78))
                    if any(k in [b"sv3d", b"st3d"] for k, _ in existing):
                        raise ValueError("Spherical metadata already present")
                    # Required codec boxes precede optional spatial metadata.
                    required = [(k, p) for k, p in existing if k not in [b"pasp", b"clap"]]
                    optional = [(k, p) for k, p in existing if k in [b"pasp", b"clap"]]
                    entry = (
                        entry[:78]
                        + b"".join(box(k, p) for k, p in required)
                        + spherical_boxes()
                        + b"".join(box(k, p) for k, p in optional)
                    )
                    count += 1
                entries.append(box(entry_kind, entry))
            return box(kind, payload[:8] + b"".join(entries))
        return box(kind, payload)

    output = visit(b"moov", data)
    if count != 1:
        raise ValueError(f"Expected one video sample entry, found {count}")
    return output


def tag_equirectangular(path):
    with open(path, "r+b") as stream:
        stream.seek(0, 2)
        length = stream.tell()
        pos = 0
        mdat_seen = False
        while pos < length:
            stream.seek(pos)
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError("Truncated MP4")
            size, kind = struct.unpack(">I4s", header)
            header_bytes = 8
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0]
                header_bytes = 16
            if size < header_bytes or pos + size > length:
                raise ValueError("Invalid top-level MP4 box")
            if kind == b"mdat":
                mdat_seen = True
            if kind == b"moov":
                if not mdat_seen or pos + size != length or header_bytes != 8:
                    raise ValueError("Only non-fragmented moov-last MP4 is supported")
                if size > 64 * 1024 * 1024:
                    raise ValueError("Oversized MP4 metadata")
                result = inject_moov(stream.read(size - header_bytes))
                stream.seek(pos)
                stream.write(result)
                stream.truncate()
                return
            pos += size
    raise ValueError("No moov box")


def shifted_chunk_offsets(moov_payload, delta):
    """Shift stco/co64 entries, promoting 32-bit tables when necessary."""
    tables = 0

    def visit(kind, payload):
        nonlocal tables
        if kind in [b"moov", b"trak", b"mdia", b"minf", b"stbl"]:
            return box(kind, b"".join(visit(k, p) for k, p in children(payload)))
        if kind in [b"stco", b"co64"]:
            if len(payload) < 8:
                raise ValueError("Truncated chunk-offset table")
            count = struct.unpack_from(">I", payload, 4)[0]
            width, code = (4, "I") if kind == b"stco" else (8, "Q")
            if len(payload) != 8 + count * width:
                raise ValueError("Invalid chunk-offset table length")
            values = [
                struct.unpack_from(">" + code, payload, 8 + i * width)[0] + delta
                for i in range(count)
            ]
            if any(v < 0 or v > 0xFFFFFFFFFFFFFFFF for v in values):
                raise ValueError("Chunk offset overflow")
            if kind == b"stco" and any(v > 0xFFFFFFFF for v in values):
                kind, code = b"co64", "Q"
            tables += 1
            return box(
                kind, payload[:8] + b"".join(struct.pack(">" + code, value) for value in values)
            )
        return box(kind, payload)

    result = visit(b"moov", moov_payload)
    if not tables:
        raise ValueError("No chunk offsets in non-fragmented MP4")
    return result


def make_faststart(source, output):
    """Move owned MP4 metadata forward without losing spatial boxes or re-encoding."""
    from pathlib import Path

    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("Fast-start output must differ from its input")
    with source.open("rb") as stream:
        stream.seek(0, 2)
        length = stream.tell()
        pos = 0
        first_end = None
        moov_payload = None
        mdat_seen = False
        while pos < length:
            stream.seek(pos)
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError("Truncated top-level MP4 box")
            size, kind = struct.unpack(">I4s", header)
            header_size = 8
            if size == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    raise ValueError("Truncated extended MP4 box")
                size = struct.unpack(">Q", extended)[0]
                header_size = 16
            if size < header_size or pos + size > length:
                raise ValueError("Invalid top-level MP4 box size")
            if pos == 0:
                if kind != b"ftyp":
                    raise ValueError("Expected ftyp as the first MP4 box")
                first_end = size
            if kind == b"moof":
                raise ValueError("Fragmented MP4 is not supported")
            if kind == b"mdat":
                mdat_seen = True
            if kind == b"moov":
                if (
                    not mdat_seen
                    or pos + size != length
                    or header_size != 8
                    or size > 64 * 1024 * 1024
                ):
                    raise ValueError("Expected bounded moov-last MP4")
                moov_start = pos
                moov_payload = stream.read(size - 8)
            pos += size
        if moov_payload is None:
            raise ValueError("No moov box")
        delta = len(moov_payload) + 8
        # Promotion to co64 can grow moov; recalculate from original offsets.
        for _ in range(16):
            moved = shifted_chunk_offsets(moov_payload, delta)
            if len(moved) == delta:
                break
            delta = len(moved)
        else:
            raise ValueError("Chunk-offset relocation did not converge")
        with output.open("xb") as dest:
            stream.seek(0)
            dest.write(stream.read(first_end))
            dest.write(moved)
            remaining = moov_start - first_end
            while remaining:
                block = stream.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Source truncated during fast-start copy")
                dest.write(block)
                remaining -= len(block)
