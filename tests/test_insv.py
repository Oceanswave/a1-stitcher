import struct

import pytest
from conftest import pb, trailer

from a1_stitcher.insv import InsvReader, protobuf_fields


@pytest.mark.parametrize("version,headers", [(1, True), (2, True), (3, False), (3, True)])
def test_indexed_versions_and_opaque_video_prefix(tmp_path, version, headers):
    path = tmp_path / "input.insv"
    data = b"opaque video" + trailer(
        [(1, pb(2, "Antigravity A1")), (3, b"sample")], version, headers
    )
    path.write_bytes(data)
    reader = InsvReader(path)
    assert reader.payload(3) == b"sample"
    assert reader.metadata()["camera_type"] == "Antigravity A1"
    assert path.read_bytes() == data


def test_adapter_roundtrip_is_metadata_only_and_never_overwrites(tmp_path):
    path = tmp_path / "source.insv"
    path.write_bytes(b"video-prefix" + trailer([(1, pb(2, "Antigravity A1")), (3, b"motion")]))
    reader = InsvReader(path)
    dest = tmp_path / "adapter.insv"
    reader.write_telemetry_adapter(dest)
    adapter = InsvReader(dest)
    assert adapter.version == 2
    assert adapter.records[3].has_trailing_header
    assert adapter.payload(3) == reader.payload(3)
    assert b"video-prefix" not in dest.read_bytes()
    with pytest.raises(FileExistsError):
        reader.write_telemetry_adapter(dest)
    with pytest.raises(ValueError):
        reader.write_telemetry_adapter(path)


@pytest.mark.parametrize(
    "mutation", ["magic", "length", "offset", "duplicate", "overlap", "version", "legacy-header"]
)
def test_corrupt_trailers_fail_closed(tmp_path, mutation):
    data = bytearray(b"prefix" + trailer([(1, b"abc"), (3, b"def")]))
    if mutation == "magic":
        data[-1] ^= 1
    if mutation == "length":
        struct.pack_into("<I", data, len(data) - 40, len(data) + 1)
    if mutation == "offset":
        struct.pack_into("<I", data, len(data) - 72 - 6 - 20 + 6, 0xFFFFFFF0)
    if mutation == "duplicate":
        data[-72 - 6 - 10] = 1
    if mutation == "overlap":
        struct.pack_into("<I", data, len(data) - 72 - 6 - 10 + 6, 1)
    if mutation == "version":
        struct.pack_into("<I", data, len(data) - 36, 99)
    if mutation == "legacy-header":
        struct.pack_into("<I", data, len(data) - 36, 2)
    path = tmp_path / "bad.insv"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        InsvReader(path)


@pytest.mark.parametrize("data", [b"", b"123", b"\0" * 77])
def test_short_files_fail(tmp_path, data):
    path = tmp_path / "short.insv"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        InsvReader(path)


@pytest.mark.parametrize(
    "payload",
    [b"\x12\x04a", b"\x08\x80", b"\x09\x00", b"\x00", b"\x0b", b"\x08" + b"\xff" * 9 + b"\x02"],
)
def test_truncated_invalid_or_overflowing_protobuf(payload):
    with pytest.raises(ValueError):
        protobuf_fields(payload)


def test_protobuf_repeated_and_fixed_fields():
    result = protobuf_fields(
        pb(1, 150) + pb(1, 5) + pb(2, b"abc") + b"\x1d" + struct.pack("<f", 1.25)
    )
    assert result[1] == [(0, 150), (0, 5)]
    assert result[2][0][1] == b"abc"
    assert struct.unpack("<f", result[3][0][1])[0] == 1.25


def test_empty_raw_imu_rejected(tmp_path):
    path = tmp_path / "empty.insv"
    path.write_bytes(trailer([(1, pb(2, "Antigravity A1") + pb(62, 1) + pb(24, 0)), (3, b"")]))
    with pytest.raises(ValueError):
        InsvReader(path).inspect()


def test_synthetic_camera_inspection(synthetic_camera):
    info = InsvReader(synthetic_camera["source"]).inspect()
    assert info["metadata"]["camera_type"] == "Antigravity A1"
    assert info["candidate_orientation_record_37"]["samples"] == 51
    assert info["candidate_orientation_record_37"]["timestamps_monotonic"]


def test_wrong_metadata_wire_type_is_an_actionable_error(tmp_path):
    path = tmp_path / "wrong-wire.insv"
    path.write_bytes(trailer([(1, pb(2, 42))]))
    with pytest.raises(ValueError, match="wire type"):
        InsvReader(path).metadata()
