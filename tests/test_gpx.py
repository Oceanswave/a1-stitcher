import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import trailer

from a1_stitcher.cli import main
from a1_stitcher.errors import StitchError
from a1_stitcher.gpx import A1_NS, GPS_SAMPLE, GPX_NS, decode_gps, export_gpx, gpx_bytes
from a1_stitcher.insv import InsvReader, Record
from a1_stitcher.render import Options, plan, stitch
from a1_stitcher.storage import digest


def sample(**changes):
    # Invented values, unrelated to any recorded location or flight.
    values = dict(
        seconds=1_700_000_000,
        millis=123,
        fix=ord("A"),
        lat=12.5,
        ns=ord("N"),
        lon=45.25,
        ew=ord("E"),
        speed=3.5,
        course=270.5,
        altitude=123.75,
    )
    values.update(changes)
    return GPS_SAMPLE.pack(*values.values())


def source_file(tmp_path, payload=None):
    source = tmp_path / "synthetic.insv"
    source.write_bytes(trailer([(7, sample() if payload is None else payload)]))
    return source


def xml_points(path):
    return ET.parse(path).findall(f".//{{{GPX_NS}}}trkpt")


def test_gpx_roundtrip_times_units_hemispheres_and_provenance(tmp_path):
    source = source_file(tmp_path, sample(ns=ord("S"), ew=ord("W")))
    output = tmp_path / "flight.gpx"
    before = digest(source)
    result = export_gpx(source, output)
    point = xml_points(output)[0]
    assert float(point.attrib["lat"]) == -12.5
    assert float(point.attrib["lon"]) == -45.25
    assert point.findtext(f"{{{GPX_NS}}}time") == "2023-11-14T22:13:20.123Z"
    assert float(point.findtext(f"{{{GPX_NS}}}ele")) == 123.75
    assert float(point.findtext(f".//{{{A1_NS}}}speedMps")) == 3.5
    assert float(point.findtext(f".//{{{A1_NS}}}courseDegrees")) == 270.5
    # Active fix does not establish 2D/3D fix quality.
    assert point.find(f"{{{GPX_NS}}}fix") is None
    assert result["points"] == 1
    assert digest(source) == before
    receipt = json.loads(Path(result["receipt"]).read_text())
    assert receipt["recipe"]["record_sha256"] == result["record_sha256"]
    assert receipt["output_sha256"] == digest(output)
    assert export_gpx(source, output, resume=True)["status"] == "reused"
    with pytest.raises(StitchError, match="already exists"):
        export_gpx(source, output)


def test_void_invalid_positions_and_time_gaps_start_new_segments(tmp_path):
    payload = b"".join(
        [
            sample(),
            sample(fix=ord("V"), seconds=0, ns=0, ew=0),
            sample(seconds=1_700_000_002),
            sample(seconds=1_700_000_003, lat=float("nan")),
            sample(seconds=1_700_000_004),
            sample(seconds=1_700_000_050),
        ]
    )
    source = source_file(tmp_path, payload)
    track = decode_gps(InsvReader(source))
    assert [len(segment) for segment in track["segments"]] == [1, 1, 1, 1]
    assert track["summary"]["void_fixes"] == 1
    assert track["summary"]["invalid_positions"] == 1
    assert track["summary"]["points"] == 4
    assert len(ET.fromstring(gpx_bytes(track)).findall(f".//{{{GPX_NS}}}trkseg")) == 4


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"", "53-byte"),
        (sample()[:-1], "53-byte"),
        (sample(fix=ord("X")), "status/hemisphere"),
        (sample(ns=ord("X")), "status/hemisphere"),
        (sample(ew=ord("X")), "status/hemisphere"),
        (sample(millis=1000), "millisecond"),
        (sample(seconds=2**64 - 1), "calendar"),
        (sample() + sample(), "strictly increasing"),
        (sample() + sample(seconds=1_699_999_999), "strictly increasing"),
        (sample(fix=ord("V")), "no valid acquired"),
        (sample(lat=91), "no valid acquired"),
        (sample(lon=float("inf")), "no valid acquired"),
    ],
)
def test_bad_data_never_creates_output(tmp_path, payload, message):
    source = source_file(tmp_path, payload)
    target = tmp_path / "uncreated" / "flight.gpx"
    with pytest.raises(StitchError, match=message):
        export_gpx(source, target)
    assert not target.parent.exists()


def test_unknown_encoding_and_size_limit_checked_before_reading(tmp_path, monkeypatch):
    reader = InsvReader(source_file(tmp_path))
    monkeypatch.setattr(reader, "payload", lambda _: pytest.fail("must not read oversized record"))
    reader.records[7] = Record(7, 1, 0, 53, False)
    with pytest.raises(StitchError, match="encoding"):
        decode_gps(reader)
    reader.records[7] = Record(7, 0, 0, 53 * 100_001, False)
    with pytest.raises(StitchError, match="sample limit"):
        decode_gps(reader)
    reader.records.clear()
    with pytest.raises(StitchError, match="No GPS record"):
        decode_gps(reader)


@pytest.mark.parametrize("gap", [True, 0, -1, float("inf"), float("nan"), "10"])
def test_gap_threshold_validation(tmp_path, gap):
    with pytest.raises(StitchError, match="gap threshold"):
        decode_gps(InsvReader(source_file(tmp_path)), gap)


def test_optional_invalid_values_are_omitted_without_discarding_position(tmp_path):
    track = decode_gps(
        InsvReader(
            source_file(tmp_path, sample(altitude=float("nan"), speed=-1, course=360, lon=180))
        )
    )
    point = ET.fromstring(gpx_bytes(track)).find(f".//{{{GPX_NS}}}trkpt")
    assert float(point.attrib["lon"]) == -180
    assert point.find(f"{{{GPX_NS}}}ele") is None
    assert point.find(f".//{{{A1_NS}}}speedMps") is None
    assert point.find(f".//{{{A1_NS}}}courseDegrees") is None
    assert track["summary"]["omitted_optional_values"] == 3


def test_french_west_hemisphere_and_signed_magnitudes(tmp_path):
    point = decode_gps(InsvReader(source_file(tmp_path, sample(lon=-45.25, ew=ord("O")))))
    assert point["segments"][0][0]["lon"] == -45.25


def test_no_clobber_symlinks_dry_run_and_wrong_extension(tmp_path):
    source = source_file(tmp_path)
    output = tmp_path / "uncreated" / "flight.gpx"
    assert export_gpx(source, output, dry_run=True)["status"] == "planned"
    assert not output.parent.exists()
    with pytest.raises(StitchError, match="overwrite"):
        export_gpx(source, source)
    with pytest.raises(StitchError, match="extension"):
        export_gpx(source, tmp_path / "flight.txt")
    link = tmp_path / "link.gpx"
    link.symlink_to(tmp_path / "missing.gpx")
    with pytest.raises(StitchError, match="already exists"):
        export_gpx(source, link)
    assert link.is_symlink()
    assert not link.exists()


def test_receipt_failure_rolls_back_gpx(tmp_path, monkeypatch):
    import a1_stitcher.gpx as module

    source = source_file(tmp_path)
    target = tmp_path / "out" / "flight.gpx"

    def fail(*args):
        raise OSError("injected disk-full error")

    monkeypatch.setattr(module, "write_new_json", fail)
    with pytest.raises(OSError, match="disk-full"):
        export_gpx(source, target)
    assert not list(target.parent.iterdir())


def test_resume_checks_settings_source_and_checksum(tmp_path):
    source = source_file(tmp_path)
    output = tmp_path / "flight.gpx"
    export_gpx(source, output)
    with pytest.raises(StitchError, match="changed"):
        export_gpx(source, output, resume=True, gap_seconds=20)
    output.write_text("corrupt")
    with pytest.raises(StitchError, match="checksum"):
        export_gpx(source, output, resume=True)


def test_standalone_cli_needs_no_ffmpeg_or_camera_calibration(tmp_path, capsys, monkeypatch):
    source = source_file(tmp_path)
    monkeypatch.setenv("PATH", "")
    output = tmp_path / "flight.gpx"
    assert main(["gpx", str(source), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["points"] == 1
    assert main(["gpx", str(source), "--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "error"


@pytest.fixture
def camera_with_gps(synthetic_camera, tmp_path):
    reader = InsvReader(synthetic_camera["source"])
    records = [(kind, reader.payload(kind)) for kind in reader.records]
    records.append((7, sample() + sample(millis=523) + sample(seconds=1_700_000_001)))
    source = tmp_path / "camera-gps.insv"
    source.write_bytes(reader.path.read_bytes()[: reader.trailer_start] + trailer(records))
    return Options(
        str(source),
        str(synthetic_camera["calibration"]),
        str(tmp_path / "out.mp4"),
        first_frame=2,
        frames=4,
        width=256,
        lens_width=128,
        threads=1,
        export_gpx=True,
    )


@pytest.mark.integration
def test_stitch_exports_entire_track_and_verifies_resume(camera_with_gps):
    config = camera_with_gps
    result = stitch(config)
    gps = result["gps"]
    assert gps["points"] == 3
    assert len(xml_points(gps["output"])) == 3
    receipt = json.loads(Path(result["receipt"]).read_text())
    assert receipt["gps"]["output_sha256"] == digest(gps["output"])
    assert stitch(replace(config, resume=True))["status"] == "reused"
    Path(gps["output"]).write_text("changed")
    with pytest.raises(StitchError, match="checksum"):
        stitch(replace(config, resume=True))


@pytest.mark.integration
def test_stitch_missing_gps_fails_before_render(synthetic_camera, camera_with_gps, monkeypatch):
    import a1_stitcher.render as module

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("must not render"))
    with pytest.raises(StitchError, match="No GPS record"):
        plan(replace(camera_with_gps, source=str(synthetic_camera["source"])))


def test_stitch_existing_gpx_is_preserved_before_decoding(camera_with_gps, monkeypatch):
    import a1_stitcher.render as module

    target = Path(camera_with_gps.output + ".gpx")
    target.write_text("existing track")
    monkeypatch.setattr(module, "read_exact", lambda *a: pytest.fail("must not decode"))
    with pytest.raises(StitchError, match="already exists"):
        stitch(camera_with_gps)
    assert target.read_text() == "existing track"
    assert not Path(camera_with_gps.output).exists()


def test_source_change_aborts_standalone_export(tmp_path, monkeypatch):
    import a1_stitcher.gpx as module

    source = source_file(tmp_path)
    target = tmp_path / "out" / "flight.gpx"
    states = iter([{"before": 1}, {"after": 2}])
    monkeypatch.setattr(module, "identity", lambda _: next(states))
    with pytest.raises(StitchError, match="Source changed"):
        export_gpx(source, target)
    assert not list(target.parent.iterdir())


def test_rounding_at_antimeridian_remains_schema_valid(tmp_path):
    track = decode_gps(InsvReader(source_file(tmp_path, sample(lon=179.9999999999))))
    point = ET.fromstring(gpx_bytes(track)).find(f".//{{{GPX_NS}}}trkpt")
    assert float(point.attrib["lon"]) == -180.0


@pytest.mark.integration
def test_stitch_receipt_failure_rolls_back_video_and_gpx(camera_with_gps, monkeypatch):
    import a1_stitcher.render as module

    def fail(*args):
        raise OSError("injected receipt failure")

    monkeypatch.setattr(module, "write_new_json", fail)
    with pytest.raises(OSError, match="receipt failure"):
        stitch(camera_with_gps)
    output = Path(camera_with_gps.output)
    assert not output.exists()
    assert not Path(str(output) + ".gpx").exists()
    assert not Path(str(output) + ".lock").exists()


def test_stitch_dry_run_and_batch_support_gpx(camera_with_gps, tmp_path, capsys):
    config = replace(camera_with_gps, output=str(tmp_path / "not-created" / "out.mp4"))
    planned = stitch(config, dry_run=True)
    assert planned["gps"]["points"] == 3
    assert "gps_data" not in planned
    assert not Path(config.output).parent.exists()
    manifest = tmp_path / "jobs.json"
    from dataclasses import asdict

    manifest.write_text(json.dumps(dict(schema_version=1, jobs=[asdict(config)])))
    assert main(["batch", str(manifest), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"][0]["gps"]["points"] == 3
    with pytest.raises(StitchError, match="boolean"):
        plan(replace(config, export_gpx="yes"))
