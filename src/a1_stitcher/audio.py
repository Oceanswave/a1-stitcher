"""Timestamp-mapped PCM companions; no silent sound loss or guessed padding."""

import tempfile
from fractions import Fraction
from pathlib import Path

from .errors import StitchError
from .process import binary, probe, run
from .storage import digest, identity, output_lock, publish_file, write_new_json


def audio_profile(info):
    tracks = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not tracks:
        return dict(status="absent")
    if len(tracks) != 1:
        raise StitchError("Expected at most one audio track; mixing is not implemented")
    track = tracks[0]
    try:
        rate, channels = int(track["sample_rate"]), int(track["channels"])
        start = Fraction(track["start_time"])
        duration = int(track["duration_ts"]) * Fraction(track["time_base"])
        samples = duration * rate
        if (
            track["codec_name"] != "aac"
            or rate != 48000
            or channels not in (1, 2)
            or duration <= 0
            or samples.denominator != 1
            or start < 0
        ):
            raise ValueError("requires one 48 kHz mono/stereo AAC track with known timestamps")
    except (KeyError, ValueError, ZeroDivisionError, TypeError) as exc:
        raise StitchError(f"Unsupported audio contract: {exc}") from exc
    return dict(
        status="timestamp-mapped-pcm-available",
        stream=track["index"],
        codec="aac",
        sample_rate=rate,
        channels=channels,
        start_seconds=str(start),
        samples=int(samples),
        sync_qualification="container timestamps only; content synchronization requires a reference",
    )


def audio_window(profile, first_frame, frames):
    if (
        type(first_frame) is not int
        or type(frames) is not int
        or first_frame < 0
        or frames < 1
        or first_frame + frames > profile["frames"]
    ):
        raise StitchError("Audio frame range exceeds the source or is invalid")
    audio = profile["audio"]
    if not isinstance(audio, dict) or audio.get("status") == "absent":
        raise StitchError("Source has no qualified audio track")
    rate, fps = audio["sample_rate"], Fraction(profile["fps"])
    origin = Fraction(profile["video_start_seconds"]) - Fraction(audio["start_seconds"])
    # Round each absolute boundary once, within half a sample. Fractional FPS
    # must not accumulate a rounded samples-per-frame error across long ranges.
    start = round((origin + first_frame / fps) * rate)
    end = round((origin + (first_frame + frames) / fps) * rate)
    if start < 0 or end > audio["samples"] or end <= start:
        raise StitchError(
            "Audio does not cover the selected video interval; no padding or shift applied"
        )
    return dict(
        first_source_frame=first_frame,
        frames=frames,
        fps=str(fps),
        first_decoded_sample=start,
        samples=end - start,
        sample_rate=rate,
        channels=audio["channels"],
        audio_stream=audio["stream"],
        video_start_seconds=profile["video_start_seconds"],
        audio_start_seconds=audio["start_seconds"],
        boundary_convention="nearest decoded sample; at most half a sample per boundary",
    )


def extract_audio(source, output, first_frame, frames):
    from .cameras import camera_adapter
    from .insv import InsvReader
    from .media import input_profile

    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    receipt = Path(str(output) + ".receipt.json")
    if output.suffix.lower() != ".wav":
        raise StitchError("PCM audio companions require a .wav output")
    if source in (output.resolve(), receipt.resolve()):
        raise StitchError("Audio output or receipt would overwrite the source")
    if any(p.exists() or p.is_symlink() for p in (output, receipt)):
        raise StitchError("Audio output and receipt must be new files")
    before = identity(source)
    metadata = InsvReader(source).metadata()
    adapter = camera_adapter(metadata)
    profile = input_profile(source, metadata)
    window = audio_window(profile, first_frame, frames)
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output_lock(output),
        tempfile.TemporaryDirectory(prefix=".a1-audio-", dir=output.parent) as work,
    ):
        staged = Path(work) / "audio.wav"
        start, end = (
            window["first_decoded_sample"],
            window["first_decoded_sample"] + window["samples"],
        )
        run(
            [
                binary("ffmpeg"),
                "-v",
                "error",
                "-xerror",
                "-n",
                "-i",
                str(source),
                "-map",
                f"0:{window['audio_stream']}",
                "-vn",
                "-af",
                f"atrim=start_sample={start}:end_sample={end},asetpts=PTS-STARTPTS",
                "-c:a",
                "pcm_f32le",
                "-map_metadata",
                "-1",
                str(staged),
            ],
            timeout=600,
        )
        track = probe(staged)["streams"][0]
        samples = int(track["duration_ts"]) * Fraction(track["time_base"]) * window["sample_rate"]
        if (
            samples != window["samples"]
            or track["codec_name"] != "pcm_f32le"
            or int(track["sample_rate"]) != window["sample_rate"]
            or track["channels"] != window["channels"]
        ):
            raise StitchError("Decoded PCM sample count or format differs from the mapped interval")
        run([binary("ffmpeg"), "-v", "error", "-xerror", "-i", str(staged), "-f", "null", "-"])
        if identity(source) != before:
            raise StitchError("Source changed during audio extraction")
        result = dict(
            kind="camera-pcm-companion-v1",
            camera_type=adapter.name,
            adapter=adapter.identifier,
            source_identity=before,
            source_frame_mapping=window,
            output_sha256=digest(staged),
            output_format="48 kHz float32 PCM WAV",
            full_decode=True,
            sync_qualification="container timestamps only; no acoustic or visual sync claim",
        )
        publish_file(staged, output)
        try:
            write_new_json(receipt, result)
        except BaseException:
            output.unlink()
            raise
    return dict(status="created", output=str(output), receipt=str(receipt), **result)
