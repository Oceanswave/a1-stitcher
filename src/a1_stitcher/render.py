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
from .errors import ProcessError, StitchError
from .insv import InsvReader
from .media import source_profile, verify
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
    width: int = 2048
    lens_width: int = 1440
    threads: int = 4
    timeout: float = 120
    no_stabilization: bool = False
    resume: bool = False
    keep_work: bool = False
    seam: str = "flow"
    rolling_shutter: str = "auto"


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
    if options.lens_width < 32 or options.lens_width > 8192 or options.lens_width % 2:
        raise StitchError("Lens decode width must be even and between 32 and 8192")
    if not 1 <= options.threads <= 64 or not np.isfinite(options.timeout) or options.timeout <= 0:
        raise StitchError("Invalid thread count or timeout")
    if not isinstance(options.no_stabilization, bool):
        raise StitchError("no_stabilization must be boolean")
    if options.seam not in ["flow", "adaptive", "feather"]:
        raise StitchError("Seam must be flow, adaptive or feather")
    source = Path(options.source).resolve(strict=True)
    calibration_path = Path(options.calibration).resolve(strict=True)
    output = Path(options.output).absolute()
    receipt = Path(str(output) + ".receipt.json")
    protected = {source, calibration_path}
    if output.resolve() in protected or receipt.resolve() in protected:
        raise StitchError("Output or receipt would overwrite an input")
    if output.suffix.lower() != ".mp4":
        raise StitchError("Output must be an MP4 path")
    reader = InsvReader(source)
    metadata = reader.metadata()
    calibration = load_calibration(calibration_path, metadata)
    lenses_from_metadata(metadata, options.lens_width)
    profile = source_profile(source, metadata)
    if options.first_frame + options.frames > profile["frames"]:
        raise StitchError("Requested frame range exceeds source video")
    times, _ = orientation37(reader)
    fps = Fraction(profile["fps"])
    readout = sensor_readout(metadata, float(fps), options.rolling_shutter)
    begin = options.first_frame / float(fps) + calibration["time_shift_seconds"]
    end = (options.first_frame + options.frames - 1) / float(fps) + calibration[
        "time_shift_seconds"
    ]
    if begin - readout / 2 < times[0] or end + readout / 2 > times[-1]:
        raise StitchError("Recorded attitude does not cover the selected video range")
    ffmpeg = binary("ffmpeg")
    version = run([ffmpeg, "-version"]).decode().splitlines()[0]
    settings = {
        k: v
        for k, v in asdict(options).items()
        if k not in ["source", "calibration", "output", "resume", "keep_work", "timeout", "threads"]
    }
    implementation = hashlib.sha256()
    for module in sorted(Path(__file__).parent.glob("*.py")):
        implementation.update(module.name.encode())
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
            model="native-row-constant-angular-velocity-v1" if readout else "off",
        ),
        color="full-range SDR BT.709 to limited-range SDR BT.709; no LUT",
    )
    return dict(
        recipe=recipe,
        recipe_sha256=fingerprint(recipe),
        output=str(output),
        receipt=str(receipt),
        warnings=[
            "Experimental image quality; review fast motion, seams and horizon before editorial use",
            "Source identity uses file stat and edge hashes, not a full-file cryptographic hash",
        ],
        reader=reader,
        metadata=metadata,
        calibration=calibration,
    )


def stitch(options, progress=None, dry_run=False):
    started = time.monotonic()
    job = plan(options)
    public_plan = {k: v for k, v in job.items() if k not in ["reader", "metadata", "calibration"]}
    if dry_run:
        return dict(status="planned", **public_plan)
    output, receipt_path = Path(job["output"]), Path(job["receipt"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        if (
            output.exists()
            or output.is_symlink()
            or receipt_path.exists()
            or receipt_path.is_symlink()
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
            return dict(
                status="reused",
                output=str(output),
                receipt=str(receipt_path),
                verification=verification,
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
            pose = Slerp(times, poses)(samples)
            mount = Rotation.from_matrix(job["calibration"]["lens_mount"])
            readout = job["recipe"]["rolling_shutter"]["readout_seconds"]
            velocities = [None] * options.frames
            if readout:
                interpolation = Slerp(times, poses)
                first = interpolation(samples - readout / 2)
                last = interpolation(samples + readout / 2)
                velocities = (mount.inv() * first.inv() * last * mount).as_rotvec() / readout
            ned_to_camera = Rotation.from_matrix([[0, 1, 0], [0, 0, 1], [1, 0, 0]])
            heading = pose[0].as_euler("xyz")[2]
            world = Rotation.from_euler("y", -heading) * ned_to_camera
            matrices = (world * pose * mount).as_matrix()
            if options.no_stabilization:
                matrices[:] = matrices[0]
            lenses = lenses_from_metadata(job["metadata"], options.lens_width)
            stitcher = TiledStitcher(
                lenses,
                job["calibration"]["rotation_lens1_to_lens0"],
                options.width,
                seam=options.seam,
                fps=float(fps),
                readout_seconds=readout,
            )
            cv2.setNumThreads(options.threads)
            ffmpeg = binary("ffmpeg")
            untagged = work / "encoded.mp4"
            ready = work / "ready.mp4"
            missing_max = 0.0
            with ExitStack() as stack:
                log = stack.enter_context((work / "decode.log").open("wb"))
                # Demux the original once. Two independent readers competed for
                # external-drive I/O. Pair decoded frame ordinals explicitly;
                # preflight requires matching constant-rate tracks/start times.
                filters = (
                    ";".join(
                        f"[0:v:{i}]scale={options.lens_width}:{options.lens_width}:"
                        f"in_color_matrix=bt709,format=bgr24,setpts=N/({float(fps):.12f}*TB)[l{i}]"
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
                    "bgr24",
                    "-f",
                    "rawvideo",
                    "-",
                ]
                decoder = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, bufsize=0)
                processes.append(decoder)
                log = stack.enter_context((work / "encode.log").open("wb"))
                encoder = subprocess.Popen(
                    [
                        ffmpeg,
                        "-v",
                        "error",
                        "-n",
                        "-f",
                        "rawvideo",
                        "-pixel_format",
                        "bgr24",
                        "-video_size",
                        f"{options.width}x{options.width // 2}",
                        "-framerate",
                        str(fps),
                        "-i",
                        "-",
                        "-vf",
                        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
                        "-c:v",
                        "libx264",
                        "-threads",
                        str(options.threads),
                        "-preset",
                        "fast",
                        "-crf",
                        "18",
                        "-color_range",
                        "tv",
                        "-colorspace",
                        "bt709",
                        "-color_primaries",
                        "bt709",
                        "-color_trc",
                        "bt709",
                        str(untagged),
                    ],
                    stdin=subprocess.PIPE,
                    stderr=log,
                    bufsize=0,
                )
                processes.append(encoder)
                for number, matrix in enumerate(matrices, start=1):
                    pair = np.frombuffer(
                        read_exact(decoder.stdout, options.lens_width**2 * 6, options.timeout),
                        np.uint8,
                    ).reshape(options.lens_width, options.lens_width * 2, 3)
                    frames = [pair[:, : options.lens_width], pair[:, options.lens_width :]]
                    sphere, missing = stitcher.stitch(frames, matrix.T, velocities[number - 1])
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
            tag_equirectangular(untagged)
            make_faststart(untagged, ready)
            expected = dict(
                width=options.width,
                height=options.width // 2,
                nb_frames=options.frames,
                fps=str(fps),
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
                max_uncovered_fraction=missing_max,
                seam_diagnostics=stitcher.seam.report() if stitcher.seam is not None else None,
                elapsed_seconds=time.monotonic() - started,
                quality_status="experimental; technical verification is not perceptual acceptance",
                warnings=job["warnings"],
                limitations=[
                    "8-bit SDR only",
                    "Per-row correction assumes locally constant angular velocity; no high-rate vibration reconstruction"
                    if readout
                    else "Per-row rolling-shutter correction disabled or metadata absent",
                    "Confidence-gated local flow cannot reconstruct occluded detail"
                    if options.seam in ["flow", "adaptive"]
                    else "Angular feather seams; no optical-flow parallax correction",
                    "No camera/propeller removal",
                    "50 Hz recorded attitude; no high-rate IMU fusion",
                ],
            )
            publish_file(ready, output)
            published = True
            try:
                write_new_json(receipt_path, receipt)
            except BaseException:
                # Remove only the same inode that this job just linked into place.
                if output.exists() and output.stat().st_ino == ready.stat().st_ino:
                    output.unlink()
                published = False
                raise
            return dict(
                status="created",
                output=str(output),
                receipt=str(receipt_path),
                verification=checked,
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
