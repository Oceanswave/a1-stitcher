"""Media profile validation and decoded output verification."""

from fractions import Fraction
from pathlib import Path

from .errors import StitchError
from .modes import require_recording_mode
from .process import binary, probe, run
from .storage import digest, load_json


def source_profile(path, metadata):
    info = probe(path)
    streams = info["streams"]
    videos = [s for s in streams if s["codec_type"] == "video"]
    if metadata.get("camera_type") != "Antigravity A1" or len(videos) != 2:
        raise StitchError("Expected an Antigravity A1 original with two lens video tracks")
    mode = require_recording_mode(metadata, "video")
    if any(s["codec_type"] == "audio" for s in streams):
        raise StitchError("Audio preservation is not implemented; refusing to silently drop it")
    if metadata.get("gamma_mode") not in [None, ""]:
        raise StitchError("Explicit camera gamma mode has not been qualified")
    counts = []
    rates = []
    dimensions = []
    starts = []
    try:
        for video in videos:
            if video.get("codec_name") not in ["h264", "hevc"]:
                raise StitchError("Expected A1 H.264 or H.265 lens tracks")
            width, height = video["width"], video["height"]
            if width != height or not 32 <= width <= 8192:
                raise StitchError("Only square lens tracks up to 8192 pixels are supported")
            if video["pix_fmt"] not in ["yuv420p", "yuvj420p"]:
                raise StitchError(
                    "Only the tested 8-bit SDR profile is supported; preserve higher-depth/log originals"
                )
            if any(
                video.get(key) != value
                for key, value in [
                    ("color_space", "bt709"),
                    ("color_transfer", "bt709"),
                    ("color_range", "pc"),
                ]
            ):
                raise StitchError(
                    "Unknown input color profile; no assumed log transform is applied"
                )
            rate = Fraction(video["r_frame_rate"])
            if rate <= 0 or rate > 120 or Fraction(video["avg_frame_rate"]) != rate:
                raise StitchError("Only known constant-frame-rate recordings are supported")
            nominal = metadata.get("frame_rate_nominal")
            if nominal is not None and (
                type(nominal) is not int
                or nominal <= 0
                or abs(float(rate) - nominal) > nominal * 0.0011
            ):
                raise StitchError(
                    "Capture and playback frame rates disagree; retimed A1 recordings need a qualified clock"
                )
            count = int(video["nb_frames"])
            if count <= 0:
                raise StitchError("Empty video track")
            counts.append(count)
            rates.append(rate)
            dimensions.append((width, height))
            starts.append(Fraction(video["start_time"]))
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        raise StitchError(f"Incomplete camera video metadata: {exc}") from exc
    if any(len(set(values)) != 1 for values in [counts, rates, dimensions, starts]):
        raise StitchError("Lens tracks have different dimensions, timing, or frame counts")
    return dict(
        fps=str(rates[0]),
        frames=counts[0],
        width=dimensions[0][0],
        color="full-range SDR BT.709",
        audio="none",
        streams=[v["index"] for v in videos],
        recording_mode=mode,
    )


def verify(path, *, expected=None, receipt=None, full=True, timeout=600):
    info = probe(path)
    streams = info["streams"]
    videos = [s for s in streams if s["codec_type"] == "video"]
    if len(videos) != 1:
        raise StitchError("Expected one output video track")
    video = videos[0]
    if video["width"] != video["height"] * 2:
        raise StitchError("Output is not a complete 2:1 sphere")
    if not any(s.get("projection") == "equirectangular" for s in video.get("side_data_list", [])):
        raise StitchError("Output lacks recognized equirectangular metadata")
    if not any(s.get("type") == "2D" for s in video.get("side_data_list", [])):
        raise StitchError("Output lacks monoscopic stereo metadata")
    if expected:
        for key in ["width", "height", "nb_frames"]:
            if int(video[key]) != int(expected[key]):
                raise StitchError(f"Output {key} does not match the planned conversion")
        if Fraction(video["r_frame_rate"]) != Fraction(expected["fps"]):
            raise StitchError("Output frame rate differs from source")
        for key in ["codec_name", "pix_fmt"]:
            if key in expected and video.get(key) != expected[key]:
                raise StitchError(f"Output {key} differs from the requested encoding")
    if any(
        video.get(key) != value
        for key, value in [
            ("color_space", "bt709"),
            ("color_transfer", "bt709"),
            ("color_primaries", "bt709"),
            ("color_range", "tv"),
        ]
    ):
        raise StitchError("Output color metadata is inconsistent with SDR processing")
    checksum = digest(path)
    if receipt is not None:
        saved = load_json(receipt)
        if saved.get("output_sha256") != checksum:
            raise StitchError("Output checksum differs from receipt")
        if "viewport_files" in saved:
            from .player import sidecar_paths

            sides = sidecar_paths(Path(path))
            if set(saved["viewport_files"]) != {p.name for p in sides}:
                raise StitchError("Viewport receipt has unexpected filenames")
            for p in sides:
                if (
                    not p.is_file()
                    or p.is_symlink()
                    or digest(p) != saved["viewport_files"][p.name]
                ):
                    raise StitchError("Viewport sidecar is missing or differs from receipt")
    if full:
        run(
            [binary("ffmpeg"), "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
            timeout=timeout,
        )
    return dict(
        width=video["width"],
        height=video["height"],
        frames=int(video["nb_frames"]),
        fps=video["r_frame_rate"],
        duration_seconds=float(video["duration"]),
        projection="equirectangular",
        stereo="monoscopic",
        output_sha256=checksum,
        full_decode=full,
        color="limited-range SDR BT.709",
        codec=video["codec_name"],
        pixel_format=video["pix_fmt"],
    )
