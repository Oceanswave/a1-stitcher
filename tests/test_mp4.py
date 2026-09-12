import struct

import pytest

from a1_stitcher.mp4 import box, children, inject_moov, tag_equirectangular


def moov():
    sample = bytes(78) + box(b"avcC", b"codec") + box(b"pasp", bytes(8))
    entry = box(b"avc1", sample)
    result = box(b"stsd", bytes(4) + struct.pack(">I", 1) + entry)
    for kind in [b"stbl", b"minf", b"mdia", b"trak"]:
        result = box(kind, result)
    return result


def test_metadata_injection_preserves_media_offsets(tmp_path):
    path = tmp_path / "own.mp4"
    prefix = box(b"ftyp", b"isom") + box(b"mdat", b"owned-video-bytes")
    path.write_bytes(prefix + box(b"moov", moov()))
    tag_equirectangular(path)
    data = path.read_bytes()
    assert data.startswith(prefix)
    assert all(kind in data for kind in [b"st3d", b"sv3d", b"svhd", b"proj", b"prhd", b"equi"])
    with pytest.raises(ValueError, match="already"):
        tag_equirectangular(path)


@pytest.mark.parametrize(
    "data", [b"x", struct.pack(">I4s", 100, b"bad!"), struct.pack(">I4s", 0, b"bad!")]
)
def test_malformed_children_rejected(data):
    with pytest.raises(ValueError):
        list(children(data))


def test_faststart_input_rejected_without_changes(tmp_path):
    path = tmp_path / "fast.mp4"
    data = box(b"moov", moov()) + box(b"mdat", b"bytes")
    path.write_bytes(data)
    with pytest.raises(ValueError, match="moov-last"):
        tag_equirectangular(path)
    assert path.read_bytes() == data


def test_missing_video_entry_rejected():
    with pytest.raises(ValueError, match="one video"):
        inject_moov(box(b"trak", b""))


def test_faststart_updates_chunk_offsets_and_keeps_spatial_boxes(tmp_path):
    from a1_stitcher.mp4 import make_faststart

    prefix = box(b"ftyp", b"isom") + box(b"mdat", b"video-payload")
    offset = len(box(b"ftyp", b"isom")) + 8
    offsets = box(b"stco", bytes(4) + struct.pack(">II", 1, offset))
    payload = box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", offsets))))
    source = tmp_path / "source.mp4"
    target = tmp_path / "target.mp4"
    source.write_bytes(prefix + box(b"moov", payload))
    make_faststart(source, target)
    data = target.read_bytes()
    index = data.index(b"stco")
    moved = struct.unpack_from(">I", data, index + 12)[0]
    assert data[moved : moved + 13] == b"video-payload"
    assert data.index(b"moov") < data.index(b"mdat")
    with pytest.raises(FileExistsError):
        make_faststart(source, target)


def test_chunk_offsets_promote_to_co64_without_overflow():
    from a1_stitcher.mp4 import shifted_chunk_offsets

    payload = box(
        b"trak",
        box(
            b"mdia",
            box(b"minf", box(b"stbl", box(b"stco", bytes(4) + struct.pack(">II", 1, 0xFFFFFFF0)))),
        ),
    )
    data = shifted_chunk_offsets(payload, 100)
    assert b"stco" not in data
    index = data.index(b"co64")
    assert struct.unpack_from(">Q", data, index + 12)[0] == 0xFFFFFFF0 + 100
