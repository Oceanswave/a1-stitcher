"""Read indexed Insta360/A1 trailer records without modifying or decoding video.

Format references: AdrianEddy/telemetry-parser (MIT/Apache-2.0), insta360/*.rs.
The A1 v3 recordings examined here address payloads directly through the offset
table; unlike the older layout, payloads have no mandatory trailing record header.
Unknown records are retained in the inventory, never guessed to be known formats.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"8db42d694ccc418790edff439fe026bf"
FOOTER_BYTES = 72
MAX_RECORD_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class Record:
    kind: int
    encoding: int
    offset: int
    size: int
    has_trailing_header: bool


class InsvReader:
    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)
        self.size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            if self.size < FOOTER_BYTES + 6:
                raise ValueError("File too short for an INSV trailer")
            stream.seek(-FOOTER_BYTES, 2)
            footer = stream.read(FOOTER_BYTES)
            if footer[40:] != MAGIC:
                raise ValueError("No recognized INSV trailer magic")
            self.trailer_bytes, self.version = struct.unpack_from("<II", footer, 32)
            if self.version not in (1, 2, 3):
                raise ValueError("Unsupported INSV trailer version")
            if not FOOTER_BYTES + 6 <= self.trailer_bytes <= self.size:
                raise ValueError("Invalid trailer length")
            self.trailer_start = self.size - self.trailer_bytes
            stream.seek(-FOOTER_BYTES - 6, 2)
            encoding, kind, length = struct.unpack("<BBI", stream.read(6))
            if kind != 0 or encoding != 0 or length % 10:
                raise ValueError("This reader requires a binary indexed trailer")
            if not length or length > min(40960, self.trailer_bytes - FOOTER_BYTES - 6):
                raise ValueError("Invalid record index length")
            self.index_start = self.size - FOOTER_BYTES - 6 - length
            stream.seek(self.index_start)
            table = stream.read(length)
            records = []
            for position in range(0, length, 10):
                kind, encoding, length, relative = struct.unpack_from("<BBII", table, position)
                if kind == 0:
                    continue
                offset = self.trailer_start + relative
                if (
                    length > MAX_RECORD_BYTES
                    or offset < self.trailer_start
                    or offset + length > self.index_start
                ):
                    raise ValueError(f"Record {kind} exceeds trailer bounds")
                if any(record.kind == kind for record in records):
                    raise ValueError(f"Duplicate record kind {kind}")
                stream.seek(offset + length)
                header = stream.read(6)
                has_header = header == struct.pack("<BBI", encoding, kind, length)
                if self.version < 3 and offset + length + 6 > self.index_start:
                    raise ValueError("Legacy record header exceeds trailer bounds")
                if self.version < 3 and not has_header:
                    raise ValueError(f"Legacy record {kind} has an invalid trailing header")
                records.append(Record(kind, encoding, offset, length, has_header))
            ordered = sorted(records, key=lambda record: record.offset)
            for a, b in zip(ordered, ordered[1:]):
                if a.offset + a.size + (6 if self.version < 3 else 0) > b.offset:
                    raise ValueError("Overlapping record payloads")
            self.records = {record.kind: record for record in records}

    def payload(self, kind):
        record = self.records[kind]
        with self.path.open("rb") as stream:
            stream.seek(record.offset)
            payload = stream.read(record.size)
        if len(payload) != record.size:
            raise ValueError("Source changed or record was truncated")
        return payload

    def metadata(self):
        if (
            1 not in self.records
            or self.records[1].encoding != 1
            or self.records[1].size > 1024 * 1024
        ):
            raise ValueError("Missing, encoded, or oversized camera metadata")
        fields = protobuf_fields(self.payload(1))
        strings = {
            2: "camera_type",
            3: "firmware",
            4: "file_type",
            5: "offset",
            22: "gamma_mode",
            53: "offset_v2",
            54: "offset_v3",
            56: "original_offset_v3",
        }
        expected_wires = {number: 2 for number in strings}
        expected_wires.update({number: 0 for number in [20, 24, 29, 40, 42, 43, 62, 175]})
        expected_wires.update({25: 1, 28: 1, 19: 2, 27: 2, 31: 2, 65: 2})
        for number, entries in fields.items():
            if number in expected_wires and any(
                wire != expected_wires[number] for wire, _ in entries
            ):
                raise ValueError(f"Unexpected protobuf wire type for metadata field {number}")
        data = {}
        for number, name in strings.items():
            if number in fields:
                value = fields[number][0][1].decode("utf-8")
                data[name] = (
                    [float(part) for part in value.split("_")]
                    if name.startswith(("offset", "original_offset")) and value
                    else value
                )
        for number, name in {
            20: "frame_rate_nominal",
            24: "first_frame_timestamp_us",
            29: "has_gyro_timestamp",
            40: "total_frames_metadata",
            42: "flowstate_online",
            43: "is_dewarp",
            62: "is_raw_gyro",
            175: "propeller_guard_status",
        }.items():
            if number in fields:
                data[name] = fields[number][0][1]
        for number, name in {25: "rolling_shutter_ms", 28: "gyro_timestamp_ms"}.items():
            if number in fields:
                data[name] = struct.unpack("<d", fields[number][0][1])[0]
        for number, name, names in [
            (19, "dimension", ["x", "y"]),
            (27, "window_crop_info", ["src_width", "src_height", "dst_width", "dst_height"]),
            (65, "gyro_configuration", ["acc_range_g", "gyro_range_dps"]),
        ]:
            if number in fields:
                nested = protobuf_fields(fields[number][0][1])
                data[name] = {
                    label: nested[i + 1][0][1] for i, label in enumerate(names) if i + 1 in nested
                }
        if 31 in fields and len(fields[31][0][1]) >= 48:
            data["gyro_calibration_values"] = list(struct.unpack_from("<6d", fields[31][0][1]))
        data["unknown_protobuf_field_numbers"] = sorted(
            set(fields) - set(strings) - {19, 20, 24, 25, 27, 28, 29, 31, 40, 42, 43, 62, 65}
        )
        return data

    def write_telemetry_adapter(self, output, kinds=(1, 3, 4)):
        """Emit a metadata-only compatibility file for telemetry-parser, not video."""
        output = Path(output)
        if output.resolve() == self.path:
            raise ValueError("Never overwrite the original")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            index = []
            for kind in kinds:
                if kind not in self.records:
                    continue
                record = self.records[kind]
                payload = self.payload(kind)
                index.append((kind, record.encoding, len(payload), stream.tell()))
                stream.write(payload)
                stream.write(struct.pack("<BBI", record.encoding, kind, len(payload)))
            table = b"".join(struct.pack("<BBII", *item) for item in index)
            stream.write(table)
            stream.write(struct.pack("<BBI", 0, 0, len(table)))
            length = stream.tell() + FOOTER_BYTES
            stream.write(bytes(32) + struct.pack("<II", length, 2) + MAGIC)

    def inspect(self):
        metadata = self.metadata()
        records = [
            dict(
                kind=r.kind,
                encoding=r.encoding,
                offset=r.offset,
                bytes=r.size,
                has_trailing_header=r.has_trailing_header,
                sha256=hashlib.sha256(self.payload(r.kind)).hexdigest(),
            )
            for r in self.records.values()
        ]
        result = dict(
            source=str(self.path),
            source_bytes=self.size,
            trailer_version=self.version,
            trailer_bytes=self.trailer_bytes,
            metadata=metadata,
            records=records,
            classification="raw camera media; not stitched, not stabilized by this inspector",
        )
        if 3 in self.records and metadata.get("is_raw_gyro"):
            payload = self.payload(3)
            if not payload or len(payload) % 20:
                raise ValueError("Raw IMU length is not divisible by 20")
            timestamps = [
                struct.unpack_from("<Q", payload, i)[0] for i in range(0, len(payload), 20)
            ]
            if any(a >= b for a, b in zip(timestamps, timestamps[1:])):
                raise ValueError("Raw IMU timestamps are not strictly increasing")
            origin = metadata["first_frame_timestamp_us"]
            result["raw_imu"] = dict(
                samples=len(timestamps),
                first_relative_seconds=(timestamps[0] - origin) / 1e6,
                last_relative_seconds=(timestamps[-1] - origin) / 1e6,
                mean_rate_hz=(len(timestamps) - 1) * 1e6 / (timestamps[-1] - timestamps[0]),
                time_convention="raw timestamps minus first video frame timestamp; no undocumented offset applied",
            )
        if 4 in self.records and metadata.get("camera_type") == "Antigravity A1":
            from .exposure import exposure_summary

            result["exposure"] = exposure_summary(self)
        if 37 in self.records:
            payload = self.payload(37)
            if payload and len(payload) % 36 == 0:
                samples = list(struct.iter_unpack("<Q7f", payload))
                norms = [
                    math.sqrt(sum(value * value for value in sample[1:5])) for sample in samples
                ]
                result["candidate_orientation_record_37"] = dict(
                    samples=len(samples),
                    first_timestamp_us=samples[0][0],
                    last_timestamp_us=samples[-1][0],
                    quaternion_norm_min=min(norms),
                    quaternion_norm_max=max(norms),
                    timestamps_monotonic=all(a[0] < b[0] for a, b in zip(samples, samples[1:])),
                    status="36-byte layout observed: uint64 timestamp, four quaternion-like floats, three unknown floats; axes and semantics require validation",
                )
        return result


def protobuf_fields(data):
    """Bounds-checked wire decoder; field meaning is supplied separately."""
    position = 0
    result = {}

    def varint():
        nonlocal position
        value = 0
        for shift in range(0, 70, 7):
            if position >= len(data):
                raise ValueError("Truncated protobuf varint")
            byte = data[position]
            position += 1
            value |= (byte & 127) << shift
            if byte < 128:
                if value > 0xFFFFFFFFFFFFFFFF:
                    raise ValueError("Protobuf varint exceeds uint64")
                return value
        raise ValueError("Oversized protobuf varint")

    while position < len(data):
        key = varint()
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("Invalid protobuf field number")
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            length = varint() if wire == 2 else 8 if wire == 1 else 4
            if position + length > len(data):
                raise ValueError("Truncated protobuf field")
            value = data[position : position + length]
            position += length
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        result.setdefault(number, []).append((wire, value))
    return result
