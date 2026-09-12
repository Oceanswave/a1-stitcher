"""Reproducible conversion jobs, bounded subprocesses, and no-clobber delivery."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import scipy
from scipy.spatial.transform import Rotation, Slerp

from . import __version__
from .calibration import load_calibration
from .encoding import check_encoder, encoder_command, encoding_profile
from .errors import ProcessError, StitchError
from .gpx import decode_gps, gpx_bytes, verify_gpx
from .insv import InsvReader
from .media import source_profile, verify
from .motion import ROW_SAMPLES, row_rotations, world_orientation
from .mp4 import make_faststart, tag_equirectangular
from .process import binary, read_exact, run, stop, write_all
from .projection import TiledStitcher, lenses_from_metadata, orientation37
from .storage import fingerprint, identity, load_json, output_lock, publish_file, write_new_json


@dataclass(frozen=True)
class Options:
    source: str
    calibration: str
    output: str
    first_frame: int
    frames: int
    width: int = 8192
    lens_width: int = 0
    threads: int = 4
    timeout: float = 120
    no_stabilization: bool = False
    resume: bool = False
    keep_work: bool = False
    seam: str = "flow"
    rolling_shutter: str = "auto"
    export_gpx: bool = False
    encoding: str = "hevc10"
    backend: str = "auto"
    gyro_profile: str | None = None
    gyro_anchor_seconds: float = 0.1
    rolling_shutter_model: str = "velocity"
    heading_reference_frame: int = 0


def sensor_readout(metadata, fps, mode):
    if mode not in ["auto", "off"]:
        raise StitchError("Rolling shutter mode must be auto or off")
    if mode == "off":
        return 0.0
    milliseconds = metadata.get("rolling_shutter_ms", 0)
    if (
        isinstance(milliseconds, bool)
        or not isinstance(milliseconds, (int, float))
        or not np.isfinite(milliseconds)
        or milliseconds < 0
        or milliseconds > 1000 / fps
    ):
        raise StitchError("Invalid embedded sensor readout duration; inspect the source metadata")
    return milliseconds / 1000


def plan(options):
    if any(
        isinstance(getattr(options, k), bool) or not isinstance(getattr(options, k), int)
        for k in ["first_frame", "frames", "width", "lens_width", "threads"]
    ):
        raise StitchError("Frame counts, dimensions and thread count must be integers")
    if options.first_frame < 0 or options.frames < 1:
        raise StitchError(
            "Source range must have a nonnegative first frame and positive frame count"
        )
    if options.width < 64 or options.width > 8192 or options.width % 4:
        raise StitchError("Output width must be a multiple of 4 between 64 and 8192")
    if options.lens_width != 0 and (
        options.lens_width < 32 or options.lens_width > 8192 or options.lens_width % 2
    ):
        raise StitchError("Lens decode width must be even and between 32 and 8192")
    if not 1 <= options.threads <= 64 or not np.isfinite(options.timeout) or options.timeout <= 0:
        raise StitchError("Invalid thread count or timeout")
    for name in ["no_stabilization", "resume", "keep_work"]:
        if not isinstance(getattr(options, name), bool):
            raise StitchError(f"{name} must be boolean")
    if not isinstance(options.export_gpx, bool):
        raise StitchError("export_gpx must be boolean")
    if options.seam not in ["flow", "adaptive", "feather"]:
        raise StitchError("Seam must be flow, adaptive or feather")
    if options.backend not in ["auto", "cpu", "metal"]:
        raise StitchError("Backend must be auto, cpu or metal")
    if options.rolling_shutter_model not in ["trajectory", "velocity"]:
        raise StitchError("Rolling shutter model must be trajectory or velocity")
    if (
        isinstance(options.heading_reference_frame, bool)
        or not isinstance(options.heading_reference_frame, int)
        or options.heading_reference_frame < -1
    ):
        raise StitchError("Heading reference frame must be -1 or a nonnegative integer")
    source = Path(options.source).resolve(strict=True)
    calibration_path = Path(options.calibration).resolve(strict=True)
    output = Path(options.output).absolute()
    receipt = Path(str(output) + ".receipt.json")
    gpx_path = Path(str(output) + ".gpx")
    protected = {source, calibration_path}
    if options.gyro_profile:
        protected.add(Path(options.gyro_profile).resolve(strict=True))
    if output.resolve() in protected or receipt.resolve() in protected:
        raise StitchError("Output or receipt would overwrite an input")
    if options.export_gpx and gpx_path.resolve() in protected:
        raise StitchError("GPX output would overwrite an input")
    encoding = encoding_profile(options.encoding)
    if output.suffix.lower() != encoding["suffix"]:
        raise StitchError(f"Encoding {options.encoding} requires a {encoding['suffix']} output")
    reader = InsvReader(source)
    metadata = reader.metadata()
    gps = decode_gps(reader) if options.export_gpx else None
    gps_data = gpx_bytes(gps) if gps else None
    calibration = load_calibration(calibration_path, metadata)
    profile = source_profile(source, metadata)
    lens_width = options.lens_width or profile["width"]
    if lens_width > profile["width"]:
        raise StitchError("Lens decode width exceeds native source resolution")
    lenses_from_metadata(metadata, lens_width)
    if options.first_frame + options.frames > profile["frames"]:
        raise StitchError("Requested frame range exceeds source video")
    times, recorded_poses = orientation37(reader)
    fps = Fraction(profile["fps"])
    readout = sensor_readout(metadata, float(fps), options.rolling_shutter)
    begin = options.first_frame / float(fps) + calibration["time_shift_seconds"]
    end = (options.first_frame + options.frames - 1) / float(fps) + calibration[
        "time_shift_seconds"
    ]
    heading_frame = (
        options.first_frame
        if options.heading_reference_frame == -1
        else options.heading_reference_frame
    )
    heading_time = heading_frame / float(fps) + calibration["time_shift_seconds"]
    if heading_frame >= profile["frames"] or not times[0] <= heading_time <= times[-1]:
        raise StitchError("Heading reference frame is outside the source/attitude range")
    if readout and options.rolling_shutter_model == "trajectory":
        selected = times[
            max(0, np.searchsorted(times, begin - readout / 2) - 1) : np.searchsorted(
                times, end + readout / 2
            )
            + 1
        ]
        if np.any(np.diff(selected) > 0.05):
            raise StitchError("Recorded attitude has gaps over 50 ms in the selected scan range")
    if begin - readout / 2 < times[0] or end + readout / 2 > times[-1]:
        raise StitchError("Recorded attitude does not cover the selected video range")
    if (
        isinstance(options.gyro_anchor_seconds, bool)
        or not np.isfinite(options.gyro_anchor_seconds)
        or not 0.02 <= options.gyro_anchor_seconds <= 1
    ):
        raise StitchError("Gyro anchor interval must be 0.02 to 1 second")
    heading_pose = Slerp(times, recorded_poses)([heading_time])[0]
    gyro = None
    if options.gyro_profile:
        from .gyro import trajectory

        motion, gyro = trajectory(reader, options.gyro_profile, options.gyro_anchor_seconds)
        heading_pose = motion(np.array([begin - readout / 2, end + readout / 2, heading_time]))[-1]
    world_orientation(heading_pose)
    ffmpeg = binary("ffmpeg")
    check_encoder(ffmpeg, encoding)
    version = run([ffmpeg, "-version"]).decode().splitlines()[0]
    from .metal import select_backend

    backend = select_backend(options.backend)
    settings = {
        k: v
        for k, v in asdict(options).items()
        if k not in ["source", "calibration", "output", "resume", "keep_work", "timeout", "threads"]
    }
    settings["lens_width"] = lens_width
    implementation = hashlib.sha256()
    for module in sorted(
        p for p in Path(__file__).parent.rglob("*") if p.suffix in [".py", ".metal", ".swift"]
    ):
        implementation.update(str(module.relative_to(Path(__file__).parent)).encode())
        implementation.update(module.read_bytes())
    recipe = dict(
        schema_version=1,
        package_version=__version__,
        implementation_sha256=implementation.hexdigest(),
        dependencies=dict(numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__),
        ffmpeg_version=version,
        source=str(source),
        source_identity=identity(source),
        calibration=calibration,
        settings=settings,
        profile=profile,
        seam="periodic-adaptive-flow-local-balance-v3"
        if options.seam == "adaptive"
        else "bidirectional-flow-local-balance-v3"
        if options.seam == "flow"
        else "angular-feather-v1",
        rolling_shutter=dict(
            readout_seconds=readout,
            model=(
                "native-row-quaternion-trajectory-v1"
                if options.rolling_shutter_model == "trajectory"
                else "native-row-constant-angular-velocity-v1"
            )
            if readout
            else "off",
            samples_per_frame=ROW_SAMPLES
            if readout and options.rolling_shutter_model == "trajectory"
            else 0,
        ),
        heading_reference=dict(source_frame=heading_frame, attitude_seconds=heading_time),
        color="full-range SDR BT.709 to limited-range SDR BT.709; no LUT",
        encoding=encoding,
        gps=gps["summary"] if gps else None,
        gyro_profile=gyro,
        backend=backend,
    )
    return dict(
        recipe=recipe,
        recipe_sha256=fingerprint(recipe),
        output=str(output),
        receipt=str(receipt),
        warnings=[
            "Experimental image quality; review fast motion, seams and horizon before editorial use",
            "Source identity uses file stat and edge hashes, not a full-file cryptographic hash",
            *(
                [backend["reason"]]
                if options.backend == "auto" and backend["name"] == "cpu"
                else []
            ),
        ],
        reader=reader,
        metadata=metadata,
        calibration=calibration,
        gps=dict(
            output=str(gpx_path),
            output_sha256=hashlib.sha256(gps_data).hexdigest(),
            **gps["summary"],
        )
        if gps
        else None,
        gps_data=gps_data,
    )


def stitch(options, progress=None, dry_run=False):
    started = time.monotonic()
    job = plan(options)
    public_plan = {
        k: v for k, v in job.items() if k not in ["reader", "metadata", "calibration", "gps_data"]
    }
    if dry_run:
        return dict(status="planned", **public_plan)
    output, receipt_path = Path(job["output"]), Path(job["receipt"])
    gpx_path = Path(job["gps"]["output"]) if job["gps"] else None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        if (
            output.exists()
            or output.is_symlink()
            or receipt_path.exists()
            or receipt_path.is_symlink()
            or (gpx_path is not None and (gpx_path.exists() or gpx_path.is_symlink()))
        ):
            if not options.resume:
                raise StitchError(
                    "Output/receipt already exists; use --resume only to verify and reuse an identical completed job"
                )
            if (
                not output.is_file()
                or not receipt_path.is_file()
                or output.is_symlink()
                or receipt_path.is_symlink()
            ):
                raise StitchError("Cannot resume: expected a completed regular video and receipt")
            saved = load_json(receipt_path)
            if saved.get("recipe_sha256") != job["recipe_sha256"]:
                raise StitchError(
                    "Cannot resume: source, calibration, settings, or processing version changed"
                )
            verification = verify(output, receipt=receipt_path, full=False)
            if job["gps"]:
                if saved.get("gps") != job["gps"]:
                    raise StitchError("GPX receipt differs from the requested export")
                verify_gpx(gpx_path, job["gps"]["output_sha256"])
            return dict(
                status="reused",
                output=str(output),
                receipt=str(receipt_path),
                verification=verification,
                gps=job["gps"],
            )
        work = Path(tempfile.mkdtemp(prefix=".a1-stitch-", dir=output.parent))
        processes = []
        published = False
        try:
            fps = Fraction(job["recipe"]["profile"]["fps"])
            times, poses = orientation37(job["reader"])
            samples = (np.arange(options.frames) + options.first_frame) / float(fps) + job[
                "calibration"
            ]["time_shift_seconds"]
            interpolation = Slerp(times, poses)
            if options.gyro_profile:
                from .gyro import trajectory

                interpolation, _ = trajectory(
                    job["reader"], options.gyro_profile, options.gyro_anchor_seconds
                )
            pose = interpolation(samples)
            mount = Rotation.from_matrix(job["calibration"]["lens_mount"])
            readout = job["recipe"]["rolling_shutter"]["readout_seconds"]
            velocities = [None] * options.frames
            if readout and options.rolling_shutter_model == "velocity":
                first = interpolation(samples - readout / 2)
                last = interpolation(samples + readout / 2)
                velocities = (mount.inv() * first.inv() * last * mount).as_rotvec() / readout
            reference = job["recipe"]["heading_reference"]["attitude_seconds"]
            world = world_orientation(interpolation([reference])[0])
            matrices = (world * pose * mount).as_matrix()
            if options.no_stabilization:
                matrices[:] = matrices[0]
            lens_width = job["recipe"]["settings"]["lens_width"]
            lenses = lenses_from_metadata(job["metadata"], lens_width)
            renderer = TiledStitcher
            if job["recipe"]["backend"]["name"] == "metal":
                from .metal import MetalStitcher

                renderer = MetalStitcher
            stitcher = renderer(
                lenses,
                job["calibration"]["rotation_lens1_to_lens0"],
                options.width,
                seam=options.seam,
                fps=float(fps),
                readout_seconds=readout,
            )
            cv2.setNumThreads(options.threads)
            ffmpeg = binary("ffmpeg")
            encoding = job["recipe"]["encoding"]
            high_precision = encoding["precision_bits"] == 16
            raw_format = encoding["raw"]
            raw_dtype = np.dtype("<u2") if high_precision else np.dtype("u1")
            untagged = work / ("encoded" + encoding["suffix"])
            ready = work / ("ready" + encoding["suffix"])
            missing_max = 0.0
            with ExitStack() as stack:
                if hasattr(stitcher, "close"):
                    stack.callback(stitcher.close)
                log = stack.enter_context((work / "decode.log").open("wb"))
                # Demux the original once. Two independent readers competed for
                # external-drive I/O. Pair decoded frame ordinals explicitly;
                # preflight requires matching constant-rate tracks/start times.
                filters = (
                    ";".join(
                        f"[0:v:{i}]scale={lens_width}:{lens_width}:"
                        f"in_color_matrix=bt709,format={raw_format},setpts=N/({float(fps):.12f}*TB)[l{i}]"
                        for i in range(2)
                    )
                    + ";[l0][l1]hstack=inputs=2:shortest=1[pair]"
                )
                command = [
                    ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-filter_complex_threads",
                    str(options.threads),
                    "-threads",
                    str(options.threads),
                    "-ss",
                    f"{options.first_frame / float(fps):.12f}",
                    "-i",
                    str(job["reader"].path),
                    "-filter_complex",
                    filters,
                    "-map",
                    "[pair]",
                    "-frames:v",
                    str(options.frames),
                    "-pix_fmt",
                    raw_format,
                    "-f",
                    "rawvideo",
                    "-",
                ]
                decoder = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, bufsize=0)
                processes.append(decoder)
                log = stack.enter_context((work / "encode.log").open("wb"))
                encoder = subprocess.Popen(
                    encoder_command(
                        ffmpeg, encoding, options.width, fps, options.threads, untagged
                    ),
                    stdin=subprocess.PIPE,
                    stderr=log,
                    bufsize=0,
                )
                processes.append(encoder)
                for number, matrix in enumerate(matrices, start=1):
                    pair = np.frombuffer(
                        read_exact(
                            decoder.stdout,
                            lens_width**2 * 6 * raw_dtype.itemsize,
                            options.timeout,
                        ),
                        raw_dtype,
                    ).reshape(lens_width, lens_width * 2, 3)
                    frames = [pair[:, :lens_width], pair[:, lens_width:]]
                    rows = None
                    if readout and options.rolling_shutter_model == "trajectory":
                        rows = row_rotations(
                            interpolation,
                            samples[number - 1],
                            mount,
                            job["calibration"]["rotation_lens1_to_lens0"],
                            readout,
                        )
                    sphere, missing = stitcher.stitch(
                        frames, matrix.T, velocities[number - 1], rows
                    )
                    missing_max = max(missing_max, missing)
                    if missing > 0.001:
                        raise StitchError(
                            "Calibration leaves uncovered sphere pixels; refusing an incomplete sphere"
                        )
                    write_all(encoder.stdin, sphere.tobytes(), options.timeout)
                    if progress and (number % 30 == 0 or number == options.frames):
                        progress(
                            dict(
                                event="progress",
                                frames=number,
                                total=options.frames,
                                elapsed_seconds=round(time.monotonic() - started, 3),
                            )
                        )
                encoder.stdin.close()
                for process in processes:
                    try:
                        code = process.wait(timeout=options.timeout)
                    except subprocess.TimeoutExpired as exc:
                        raise ProcessError(
                            "Video process did not finish within the timeout"
                        ) from exc
                    if code:
                        errors = "\n".join(
                            p.read_text(errors="replace")[-1500:] for p in work.glob("*.log")
                        )
                        raise ProcessError(f"Video process exited {code}: {errors}")
            tag_equirectangular(untagged, prores_video_range=encoding["name"] == "prores")
            make_faststart(untagged, ready)
            expected = dict(
                width=options.width,
                height=options.width // 2,
                nb_frames=options.frames,
                fps=str(fps),
                codec_name=encoding["codec"],
                pix_fmt=encoding["pixel_format"],
            )
            checked = verify(
                ready,
                expected=expected,
                timeout=max(options.timeout, options.frames / float(fps) * 4),
            )
            if identity(job["reader"].path) != job["recipe"]["source_identity"]:
                raise StitchError("Original changed during conversion; output not published")
            receipt = dict(
                schema_version=1,
                status="complete",
                package_version=__version__,
                output=str(output),
                recipe_sha256=job["recipe_sha256"],
                recipe=job["recipe"],
                output_sha256=checked["output_sha256"],
                verification=checked,
                gps=job["gps"],
                max_uncovered_fraction=missing_max,
                seam_diagnostics=stitcher.seam.report() if stitcher.seam is not None else None,
                elapsed_seconds=time.monotonic() - started,
                gpu_kernel_seconds=getattr(stitcher, "gpu_seconds", None),
                quality_status="experimental; technical verification is not perceptual acceptance",
                warnings=job["warnings"],
                limitations=[
                    "Only tested 8-bit SDR inputs; higher-precision processing does not add captured dynamic range",
                    (
                        "Per-row quaternion trajectory; accuracy is limited by attitude timing and sampling, no motion deblurring"
                        if options.rolling_shutter_model == "trajectory"
                        else "Per-row correction assumes locally constant angular velocity"
                    )
                    if readout
                    else "Per-row rolling-shutter correction disabled or metadata absent",
                    "Confidence-gated local flow cannot reconstruct occluded detail"
                    if options.seam in ["flow", "adaptive"]
                    else "Angular feather seams; no optical-flow parallax correction",
                    "No camera/propeller removal",
                    "Experimental gyro interpolation anchored to recorded attitude; high-frequency image timing not yet qualified"
                    if options.gyro_profile
                    else "50 Hz recorded attitude; no high-rate IMU fusion",
                ],
            )
            ready_gpx = work / "flight.gpx"
            if gpx_path is not None:
                ready_gpx.write_bytes(job["gps_data"])
            publish_file(ready, output)
            published = True
            gpx_published = False
            try:
                if gpx_path is not None:
                    publish_file(ready_gpx, gpx_path)
                    gpx_published = True
                write_new_json(receipt_path, receipt)
            except BaseException:
                # Remove only the same inode that this job just linked into place.
                if output.exists() and output.stat().st_ino == ready.stat().st_ino:
                    output.unlink()
                if (
                    gpx_published
                    and gpx_path.exists()
                    and gpx_path.stat().st_ino == ready_gpx.stat().st_ino
                ):
                    gpx_path.unlink()
                published = False
                raise
            return dict(
                status="created",
                output=str(output),
                receipt=str(receipt_path),
                verification=checked,
                gps=job["gps"],
                elapsed_seconds=receipt["elapsed_seconds"],
                warnings=job["warnings"],
            )
        finally:
            for process in processes:
                stop(process)
            if not options.keep_work:
                shutil.rmtree(work)
            elif progress:
                progress(dict(event="work_directory", path=str(work), published=published))
