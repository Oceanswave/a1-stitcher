"""Public command line. JSON stdout, progress/error JSON on stderr."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from . import __version__
from .errors import StitchError
from .process import binary, run
from .storage import load_json, write_new_json


def emit(value, stream=None):
    if stream is None:
        stream = sys.stdout
    print(json.dumps(value, allow_nan=False), file=stream, flush=True)


def doctor():
    import cv2
    import numpy
    import scipy

    paths = {name: binary(name) for name in ["ffmpeg", "ffprobe"]}
    encoders = run([paths["ffmpeg"], "-hide_banner", "-encoders"]).decode()
    decoders = run([paths["ffmpeg"], "-hide_banner", "-decoders"]).decode()
    if "libx265" not in encoders or "hevc" not in decoders:
        raise StitchError("FFmpeg must provide the default libx265 encoder and HEVC decoder")
    if not hasattr(cv2, "SIFT_create"):
        raise StitchError("OpenCV SIFT support is required for calibration")
    return dict(
        status="ok",
        version=__version__,
        python=platform.python_version(),
        platform=platform.system(),
        numpy=numpy.__version__,
        scipy=scipy.__version__,
        opencv=cv2.__version__,
        ffmpeg=run([paths["ffmpeg"], "-version"]).decode().splitlines()[0],
        binaries=paths,
        encoding_support={
            name: encoder in encoders
            for name, encoder in [
                ("hevc10", "libx265"),
                ("h264", "libx264"),
                ("prores", "prores_ks"),
            ]
        },
    )


def frames_csv(text):
    try:
        values = [int(v.strip()) for v in text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected comma-separated integer frame indices") from exc
    if not values or any(v < 0 for v in values):
        raise argparse.ArgumentTypeError("Frame indices must be nonnegative")
    return values


def parser():
    p = argparse.ArgumentParser(
        prog="a1-stitch",
        description="Independent A1-to-equirectangular preparation; experimental image quality.",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check dependencies and FFmpeg capabilities")
    inspect = sub.add_parser("inspect", help="Read bounded trailer, camera and attitude metadata")
    inspect.add_argument("source")
    inspect.add_argument("--output")
    inspect.add_argument("--redact-path", action="store_true")
    gpx = sub.add_parser("gpx", help="Export the source recording's GPS track as GPX 1.1")
    gpx.add_argument("source")
    gpx.add_argument("--output", required=True)
    gpx.add_argument("--gap-seconds", type=float, default=10.0)
    gpx.add_argument("--resume", action="store_true")
    gpx.add_argument("--dry-run", action="store_true")
    gyro = sub.add_parser(
        "gyro-calibrate",
        help="Fit a rigid raw-gyro profile and validate transfer on a second recording",
    )
    gyro.add_argument("source")
    gyro.add_argument("--validation-source", required=True)
    gyro.add_argument("--output", required=True)
    sync = sub.add_parser(
        "sync-calibrate", help="Fit image/gyro timing and native-row readout with temporal holdouts"
    )
    sync.add_argument("source")
    sync.add_argument("--calibration", required=True)
    sync.add_argument("--gyro-profile", required=True)
    sync.add_argument("--first-frame", required=True, type=int)
    sync.add_argument("--frames", required=True, type=int)
    sync.add_argument("--step", type=int, default=3)
    sync.add_argument("--gyro-anchor-seconds", type=float, default=0.1)
    sync.add_argument("--output", required=True)
    sync.add_argument("--evidence-dir", required=True)
    proposal = sub.add_parser(
        "mask-propose",
        help="Find persistent native obstructions; create a proposal requiring review",
    )
    proposal.add_argument("source")
    proposal.add_argument("--calibration", required=True)
    proposal.add_argument("--first-frame", required=True, type=int)
    proposal.add_argument("--frames", required=True, type=int)
    proposal.add_argument("--samples", default=24, type=int)
    proposal.add_argument("--output", required=True)
    proposal.add_argument("--evidence-dir", required=True)
    approval = sub.add_parser(
        "mask-approve", help="Activate a reviewed native obstruction proposal"
    )
    approval.add_argument("input")
    approval.add_argument("--output", required=True)
    approval.add_argument("--review-notes", required=True)
    bench = sub.add_parser(
        "benchmark", help="Compare every frame of a contiguous interval with six fixed views"
    )
    bench.add_argument("candidate")
    bench.add_argument("--reference", required=True)
    bench.add_argument("--reference-first-frame", required=True, type=int)
    bench.add_argument("--frames", required=True, type=int)
    bench.add_argument("--width", default=1024, type=int)
    bench.add_argument("--output-dir", required=True)
    cal = sub.add_parser(
        "calibrate", help="Fit unit-specific geometry and attitude against a stitched reference"
    )
    cal.add_argument("source")
    cal.add_argument("--reference", required=True)
    cal.add_argument("--first-source-frame", required=True, type=int)
    cal.add_argument("--samples", type=frames_csv, default=frames_csv("0,15,30,60,120,240,480"))
    cal.add_argument("--holdouts", type=frames_csv, required=True)
    cal.add_argument("--output", required=True)
    cal.add_argument("--evidence-dir")
    cal.add_argument(
        "--frame-clock",
        choices=["nominal", "exposure"],
        default="nominal",
        help="Refit mounting/time alignment with frame-indexed exposure midpoints",
    )
    mask = sub.add_parser("mask-template", help="Create a camera-bound native visibility template")
    mask.add_argument("source")
    mask.add_argument("--output", required=True)
    preview = sub.add_parser("mask-preview", help="Inspect native lens exclusions as red overlays")
    preview.add_argument("source")
    preview.add_argument("--occlusion-profile", required=True)
    preview.add_argument("--frame", required=True, type=int)
    preview.add_argument("--output-dir", required=True)
    migrate = sub.add_parser(
        "migrate-calibration", help="Explicitly migrate a calibration from the initial prototype"
    )
    migrate.add_argument("input")
    migrate.add_argument("--output", required=True)
    comparison = sub.add_parser(
        "compare", help="Compare mapped sphere frames to a Studio reference"
    )
    comparison.add_argument("candidate")
    comparison.add_argument("--reference", required=True)
    comparison.add_argument("--samples", type=frames_csv, required=True)
    comparison.add_argument("--reference-first-frame", type=int, required=True)
    comparison.add_argument("--output-dir", required=True)
    comparison.add_argument("--width", type=int, default=2048)
    stitch = sub.add_parser(
        "stitch", help="Convert an original source frame range into a verified standard sphere"
    )
    stitch.add_argument("source")
    stitch.add_argument(
        "--calibration",
        help="Optional reference profile; otherwise derive geometry from the original",
    )
    stitch.add_argument(
        "--view",
        choices=["pilot", "fixed"],
        default="pilot",
        help="Pilot path and guided viewer by default; fixed exports only the stabilized sphere",
    )
    stitch.add_argument("--first-frame", required=True, type=int)
    stitch.add_argument("--frames", required=True, type=int)
    stitch.add_argument("--output", required=True)
    stitch.add_argument(
        "--width", default=8192, type=int, help="Sphere width; default 8192 (full 8K)"
    )
    stitch.add_argument(
        "--lens-width", default=0, type=int, help="Native lens resolution by default (0)"
    )
    stitch.add_argument("--threads", default=4, type=int)
    stitch.add_argument("--backend", choices=["auto", "cpu", "metal"], default="auto")
    stitch.add_argument(
        "--gyro-profile", help="Optional per-unit experimental gyro interpolation profile"
    )
    stitch.add_argument(
        "--occlusion-profile", help="Camera-bound native visibility masks for body/guard exclusion"
    )
    stitch.add_argument(
        "--gyro-anchor-seconds",
        type=float,
        default=0.1,
        help="Experimental gyro anchor spacing, 0.02–1 seconds; used only with --gyro-profile",
    )
    stitch.add_argument(
        "--encoding",
        choices=["h264", "hevc10", "prores"],
        default="hevc10",
        help="8-bit H.264 review, 10-bit HEVC MP4, or 10-bit ProRes 422 HQ MOV",
    )
    stitch.add_argument(
        "--timeout", default=120, type=float, help="Maximum seconds for a stalled frame/process"
    )
    stitch.add_argument("--no-stabilization", action="store_true")
    stitch.add_argument(
        "--heading-reference-frame",
        type=int,
        default=0,
        help="Source frame defining fixed sphere heading (default 0); -1 uses selected clip start",
    )
    stitch.add_argument(
        "--rolling-shutter-model",
        choices=["trajectory", "velocity"],
        default="velocity",
        help="Experimental orientation samples through each scan, or the proven average velocity (default)",
    )
    stitch.add_argument(
        "--rolling-shutter",
        choices=["auto", "off"],
        default="auto",
        help="Correct native sensor-row timing using embedded readout duration, or disable it",
    )
    stitch.add_argument(
        "--seam",
        choices=["flow", "adaptive", "multiband", "feather"],
        default="flow",
        help="Fixed flow (default), experimental adaptive seam, or legacy feather blending",
    )
    stitch.add_argument(
        "--resume",
        action="store_true",
        help="Reuse only an identical, checksum-verified completed job",
    )
    stitch.add_argument("--keep-work", action="store_true")
    stitch.add_argument(
        "--export-gpx",
        action="store_true",
        help="Also export the entire source GPS track to OUTPUT.mp4.gpx; requires valid GPS",
    )
    stitch.add_argument("--dry-run", action="store_true")
    photo = sub.add_parser(
        "photo", help="Export an A1 INSP as a 16-bit equirectangular TIFF with panorama XMP"
    )
    photo.add_argument("source")
    photo.add_argument("--output", required=True)
    photo.add_argument(
        "--calibration", help="Optional matching lens profile; default fits original overlap"
    )
    photo.add_argument(
        "--width", type=int, default=0, help="Native combined width by default; no upscaling"
    )
    photo.add_argument("--backend", choices=["auto", "cpu", "metal"], default="auto")
    photo.add_argument("--seam", choices=["flow", "multiband", "feather"], default="flow")
    photo.add_argument("--resume", action="store_true")
    photo.add_argument("--dry-run", action="store_true")
    photo_check = sub.add_parser(
        "verify-photo", help="Decode and check TIFF precision and panorama metadata"
    )
    photo_check.add_argument("photo")
    photo_check.add_argument("--receipt")
    viewer = sub.add_parser(
        "view", help="Serve a pilot-guided export in a local interactive sphere player"
    )
    viewer.add_argument("video")
    viewer.add_argument("--port", type=int, default=8778)
    check = sub.add_parser(
        "verify", help="Validate sphere metadata, timing, color, checksum and full decode"
    )
    check.add_argument("video")
    check.add_argument("--receipt")
    check.add_argument(
        "--quick", action="store_true", help="Skip the full decode; metadata and checksum only"
    )
    check.add_argument("--timeout", type=float, default=600)
    batch = sub.add_parser("batch", help="Run a JSON list of original-source conversion jobs")
    batch.add_argument("manifest")
    batch.add_argument("--resume", action="store_true")
    batch.add_argument("--dry-run", action="store_true")
    return p


def main(argv=None):
    args = parser().parse_args(argv)

    def progress(value):
        emit(value, sys.stderr)

    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "photo":
            from .photo import export_photo

            values = vars(args).copy()
            values.pop("command")
            result = export_photo(**values)
        elif args.command == "verify-photo":
            from .photo import verify_photo

            result = verify_photo(args.photo, args.receipt)
        elif args.command == "view":
            from .player import serve

            serve(args.video, args.port, progress)
            return 0
        elif args.command == "sync-calibrate":
            from .visual_sync import calibrate

            result = calibrate(
                args.source,
                args.calibration,
                args.gyro_profile,
                args.first_frame,
                args.frames,
                args.output,
                args.evidence_dir,
                args.step,
                args.gyro_anchor_seconds,
            )
        elif args.command == "mask-propose":
            from .mask_proposal import propose

            result = propose(
                args.source,
                args.calibration,
                args.first_frame,
                args.frames,
                args.samples,
                args.output,
                args.evidence_dir,
            )
        elif args.command == "mask-approve":
            from .mask_proposal import approve

            result = approve(args.input, args.output, args.review_notes)
        elif args.command == "benchmark":
            from .benchmark import benchmark

            result = benchmark(
                args.candidate,
                args.reference,
                args.reference_first_frame,
                args.frames,
                args.output_dir,
                args.width,
            )
        elif args.command == "gyro-calibrate":
            from .gyro import calibrate

            result = calibrate(args.source, args.validation_source, args.output)
        elif args.command == "gpx":
            from .gpx import export_gpx

            result = export_gpx(
                args.source,
                args.output,
                gap_seconds=args.gap_seconds,
                resume=args.resume,
                dry_run=args.dry_run,
            )
        elif args.command == "inspect":
            from .insv import InsvReader

            result = InsvReader(args.source).inspect()
            if args.redact_path:
                result["source"] = Path(args.source).name
            if args.output:
                if Path(args.output).resolve() == Path(args.source).resolve():
                    raise StitchError("Inspection output would overwrite the source")
                write_new_json(args.output, result)
        elif args.command == "mask-preview":
            from .occlusion import preview

            result = preview(args.source, args.occlusion_profile, args.frame, args.output_dir)
        elif args.command == "mask-template":
            from .insv import InsvReader
            from .occlusion import template

            result = template(InsvReader(args.source).metadata())
            write_new_json(args.output, result)
        elif args.command == "migrate-calibration":
            from .calibration import migrate_legacy

            result = migrate_legacy(load_json(args.input))
            write_new_json(args.output, result)
        elif args.command == "calibrate":
            from .reference import calibrate

            result = calibrate(
                args.source,
                args.reference,
                args.first_source_frame,
                args.samples,
                args.holdouts,
                args.output,
                evidence=args.evidence_dir,
                frame_clock=args.frame_clock,
                progress=progress,
            )
        elif args.command == "verify":
            from .media import verify

            result = verify(
                args.video, receipt=args.receipt, full=not args.quick, timeout=args.timeout
            )
        elif args.command == "compare":
            from .compare import compare

            result = compare(
                args.candidate,
                args.reference,
                args.samples,
                args.reference_first_frame,
                args.output_dir,
                args.width,
            )
        elif args.command == "stitch":
            from .render import Options, stitch

            values = vars(args).copy()
            values.pop("command")
            dry_run = values.pop("dry_run")
            result = stitch(Options(**values), progress=progress, dry_run=dry_run)
        elif args.command == "batch":
            from .render import Options, plan, stitch

            manifest_path = Path(args.manifest).resolve(strict=True)
            manifest = load_json(manifest_path)
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_version") != 1
                or not isinstance(manifest.get("jobs"), list)
            ):
                raise StitchError("Batch manifest requires schema_version 1 and a jobs list")
            if not 1 <= len(manifest["jobs"]) <= 1000:
                raise StitchError("Batch must contain 1–1000 jobs")
            jobs = []
            for raw in manifest["jobs"]:
                if not isinstance(raw, dict):
                    raise StitchError("Each batch job must be an object")
                row = raw.copy()
                row.setdefault("calibration", None)
                for name in [
                    "source",
                    "calibration",
                    "output",
                    "gyro_profile",
                    "occlusion_profile",
                ]:
                    if name in ["calibration", "gyro_profile", "occlusion_profile"] and not row.get(
                        name
                    ):
                        continue
                    path = Path(row[name])
                    row[name] = str(path if path.is_absolute() else manifest_path.parent / path)
                row["resume"] = args.resume or row.get("resume", False)
                try:
                    jobs.append(Options(**row))
                except TypeError as exc:
                    raise StitchError(f"Invalid job fields: {exc}") from exc
            if len({Path(j.output).resolve() for j in jobs}) != len(jobs):
                raise StitchError("Batch output paths must be unique")
            outputs = {Path(j.output).resolve() for j in jobs} | {
                Path(str(j.output) + ".receipt.json").resolve() for j in jobs
            }
            outputs |= {Path(str(j.output) + ".gpx").resolve() for j in jobs if j.export_gpx}
            from .player import sidecar_paths

            outputs |= {
                p.resolve() for j in jobs if j.view == "pilot" for p in sidecar_paths(j.output)
            }
            inputs = (
                {Path(j.source).resolve() for j in jobs}
                | {Path(j.calibration).resolve() for j in jobs if j.calibration}
                | {Path(j.gyro_profile).resolve() for j in jobs if j.gyro_profile}
                | {Path(j.occlusion_profile).resolve() for j in jobs if j.occlusion_profile}
                | {manifest_path}
            )
            if outputs & inputs:
                raise StitchError("Batch outputs collide with inputs")
            # Preflight every job before starting a possibly long batch.
            for job in jobs:
                plan(job)
            result = dict(
                status="complete",
                jobs=[stitch(job, progress=progress, dry_run=args.dry_run) for job in jobs],
            )
        emit(result)
        return 0
    except KeyboardInterrupt:
        emit(
            dict(
                status="cancelled",
                error="Interrupted; originals and completed outputs were preserved",
            ),
            sys.stderr,
        )
        return 130
    except (StitchError, ValueError, OSError, KeyError, TypeError) as exc:
        emit(dict(status="error", error=str(exc)), sys.stderr)
        return 1
