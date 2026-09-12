"""Bounded GPS record 7 decoding and GPX 1.1 export, independent of video rendering.

The observed 53-byte layout agrees with public telemetry-parser and ExifTool
field descriptions. No vendor code or telemetry is included. Altitude's vertical
datum and precise GPS-to-video clock alignment remain unqualified.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import __version__
from .errors import StitchError
from .insv import InsvReader
from .storage import digest, identity, load_json, output_lock, publish_file, write_new_json

GPS_SAMPLE = struct.Struct("<QHBdBdBddd")
MAX_GPS_SAMPLES = 100_000
GPX_NS = "http://www.topografix.com/GPX/1/1"
A1_NS = "https://github.com/Oceanswave/a1-stitcher/xmlns/flight/1"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def utc_text(milliseconds):
    try:
        value = EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, ValueError) as exc:
        raise StitchError("GPS UTC timestamp is outside the supported calendar") from exc
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def decode_gps(reader, gap_seconds=10.0):
    """Return recorded positions in their original order; never interpolate a route."""
    if (
        isinstance(gap_seconds, bool)
        or not isinstance(gap_seconds, (int, float))
        or not math.isfinite(gap_seconds)
        or gap_seconds <= 0
    ):
        raise StitchError("GPS gap threshold must be a finite positive number of seconds")
    record = reader.records.get(7)
    if record is None:
        raise StitchError("No GPS record (7) in this source; IMU alone cannot supply a GPX route")
    if record.encoding != 0:
        raise StitchError("Unsupported GPS record encoding; expected binary record 7")
    if not record.size or record.size % GPS_SAMPLE.size:
        raise StitchError("GPS record must contain complete 53-byte samples")
    if record.size // GPS_SAMPLE.size > MAX_GPS_SAMPLES:
        raise StitchError("GPS record exceeds the 100000-sample limit")
    payload = reader.payload(7)
    segments, segment = [], []
    previous_time = None
    void = invalid = omitted = 0

    def end_segment():
        nonlocal segment
        if segment:
            segments.append(segment)
            segment = []

    for ordinal, sample in enumerate(GPS_SAMPLE.iter_unpack(payload)):
        seconds, millis, fix, lat, ns, lon, ew, speed, course, altitude = sample
        if fix == ord("V"):
            void += 1
            end_segment()
            continue
        if fix != ord("A") or ns not in b"NS" or ew not in b"EWO":
            raise StitchError(f"Unsupported GPS status/hemisphere at sample {ordinal}")
        if millis >= 1000:
            raise StitchError(f"Invalid GPS millisecond field at sample {ordinal}")
        timestamp = seconds * 1000 + millis
        time_text = utc_text(timestamp)
        if previous_time is not None and timestamp <= previous_time:
            raise StitchError("Acquired GPS timestamps must be strictly increasing")
        if previous_time is not None and timestamp - previous_time > gap_seconds * 1000:
            end_segment()
        previous_time = timestamp
        if not (math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180):
            invalid += 1
            end_segment()
            continue
        lat = abs(lat) * (-1 if ns == ord("S") else 1)
        lon = abs(lon) * (-1 if ew in b"WO" else 1)
        # GPX's longitude upper bound is exclusive; these meridians are identical.
        lon = -180.0 if lon == 180 else lon
        point = dict(sample=ordinal, utc_ms=timestamp, time=time_text, lat=lat, lon=lon)
        for key, value, valid in [
            ("elevation_m", altitude, math.isfinite(altitude)),
            ("speed_mps", speed, math.isfinite(speed) and speed >= 0),
            ("course_degrees", course, math.isfinite(course) and 0 <= course < 360),
        ]:
            if valid:
                point[key] = value
            else:
                omitted += 1
        segment.append(point)
    end_segment()
    if not segments:
        raise StitchError("GPS record has no valid acquired positions; no GPX was written")
    points = [p for segment in segments for p in segment]
    return dict(
        segments=segments,
        summary=dict(
            schema_version=1,
            record_kind=7,
            record_sha256=hashlib.sha256(payload).hexdigest(),
            samples=record.size // GPS_SAMPLE.size,
            points=len(points),
            segments=len(segments),
            void_fixes=void,
            invalid_positions=invalid,
            omitted_optional_values=omitted,
            first_utc=points[0]["time"],
            last_utc=points[-1]["time"],
            duration_seconds=(points[-1]["utc_ms"] - points[0]["utc_ms"]) / 1000,
            gap_seconds=gap_seconds,
            scope="all recorded GPS samples in this source; not trimmed to video selection",
            altitude="camera-reported metres; vertical datum unverified, not height above ground",
            synchronization="recorded GPS UTC; no frame-accurate GPS-to-video mapping asserted",
        ),
    )


def gpx_bytes(track):
    ET.register_namespace("", GPX_NS)
    ET.register_namespace("a1", A1_NS)

    def child(parent, name, value=None, *, extension=False, **attributes):
        namespace = A1_NS if extension else GPX_NS
        node = ET.SubElement(parent, f"{{{namespace}}}{name}", attributes)
        if value is not None:
            node.text = str(value)
        return node

    root = ET.Element(f"{{{GPX_NS}}}gpx", version="1.1", creator=f"A1 Stitcher {__version__}")
    meta = child(root, "metadata")
    child(meta, "desc", "Recorded A1 GPS track. Camera-reported elevation datum is unverified.")
    child(meta, "time", track["summary"]["first_utc"])
    trk = child(root, "trk")
    child(trk, "name", "A1 flight recording")
    extensions = child(trk, "extensions")
    child(extensions, "altitudeDatum", "unverified", extension=True)
    child(extensions, "scope", "entire-source-recording", extension=True)
    for points in track["segments"]:
        segment = child(trk, "trkseg")
        for point in points:
            longitude = f"{point['lon']:.9f}"
            if longitude == "180.000000000":
                longitude = "-180.000000000"
            node = child(segment, "trkpt", lat=f"{point['lat']:.9f}", lon=longitude)
            if "elevation_m" in point:
                child(node, "ele", f"{point['elevation_m']:.6f}")
            child(node, "time", point["time"])
            extensions = child(node, "extensions")
            child(extensions, "sampleIndex", point["sample"], extension=True)
            child(extensions, "fixStatus", "A", extension=True)
            for key, name in [("speed_mps", "speedMps"), ("course_degrees", "courseDegrees")]:
                if key in point:
                    child(extensions, name, f"{point[key]:.6f}", extension=True)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def verify_gpx(path, expected_sha256):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or digest(path) != expected_sha256:
        raise StitchError("GPX output is missing, is a symlink, or differs from its checksum")


def export_gpx(source, output, *, gap_seconds=10.0, resume=False, dry_run=False):
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    receipt_path = Path(str(output) + ".receipt.json")
    if source in {output.resolve(), receipt_path.resolve()}:
        raise StitchError("GPX output or receipt would overwrite the source")
    if output.suffix.lower() != ".gpx":
        raise StitchError("GPS output must use a .gpx extension")
    before = identity(source)
    track = decode_gps(InsvReader(source), gap_seconds)
    data = gpx_bytes(track)
    checksum = hashlib.sha256(data).hexdigest()
    recipe = dict(source=str(source), source_identity=before, **track["summary"])
    result = dict(output=str(output), receipt=str(receipt_path), **track["summary"])
    if dry_run:
        return dict(status="planned", **result)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        if any(p.exists() or p.is_symlink() for p in (output, receipt_path)):
            if not resume:
                raise StitchError(
                    "GPX output/receipt already exists; use --resume for identical reuse"
                )
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise StitchError("Cannot resume GPX without its regular receipt")
            saved = load_json(receipt_path)
            if saved.get("recipe") != recipe or saved.get("output_sha256") != checksum:
                raise StitchError(
                    "GPX source, settings or implementation changed; use a new output"
                )
            verify_gpx(output, checksum)
            return dict(status="reused", output_sha256=checksum, **result)
        if identity(source) != before:
            raise StitchError("Source changed during GPS extraction")
        fd, temporary = tempfile.mkstemp(prefix=".a1-gpx-", dir=output.parent)
        staged = Path(temporary)
        published = False
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            publish_file(staged, output)
            published = True
            write_new_json(
                receipt_path,
                dict(
                    status="complete",
                    package_version=__version__,
                    recipe=recipe,
                    output_sha256=checksum,
                ),
            )
        except BaseException:
            if published and output.exists() and output.stat().st_ino == staged.stat().st_ino:
                output.unlink()
            raise
        finally:
            staged.unlink(missing_ok=True)
    return dict(status="created", output_sha256=checksum, **result)
