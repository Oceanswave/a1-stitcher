"""Explicit review and finishing encodes; source SDR qualification is unchanged."""

from .errors import StitchError
from .process import run


def encoding_profile(name):
    profiles = {
        "h264": dict(
            encoder="libx264",
            codec="h264",
            pixel_format="yuv420p",
            raw="bgr24",
            suffix=".mp4",
            precision_bits=8,
            settings=["-preset", "fast", "-crf", "18"],
        ),
        "hevc10": dict(
            encoder="libx265",
            codec="hevc",
            pixel_format="yuv420p10le",
            raw="bgr48le",
            suffix=".mp4",
            precision_bits=16,
            settings=["-preset", "medium", "-crf", "12", "-tag:v", "hvc1"],
        ),
        "prores": dict(
            encoder="prores_ks",
            codec="prores",
            pixel_format="yuv422p10le",
            raw="bgr48le",
            suffix=".mov",
            precision_bits=16,
            settings=["-profile:v", "3"],
        ),
    }
    if name not in profiles:
        raise StitchError("Encoding must be h264, hevc10 or prores")
    return dict(name=name, **profiles[name])


def check_encoder(ffmpeg, profile):
    listing = run([ffmpeg, "-hide_banner", "-encoders"]).decode()
    names = {row.split()[1] for row in listing.splitlines() if len(row.split()) >= 2}
    if profile["encoder"] not in names:
        raise StitchError(f"FFmpeg lacks the requested {profile['encoder']} encoder")


def encoder_command(ffmpeg, profile, width, fps, threads, output):
    settings = profile["settings"].copy()
    if profile["name"] == "hevc10":
        # x265 manages its own pool; constrain it as well as FFmpeg's thread count.
        settings += ["-x265-params", f"pools={threads}:frame-threads=1:log-level=error"]
    return [
        ffmpeg,
        "-v",
        "error",
        "-n",
        "-f",
        "rawvideo",
        "-pixel_format",
        profile["raw"],
        "-video_size",
        f"{width}x{width // 2}",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-vf",
        f"scale=out_color_matrix=bt709:out_range=tv,format={profile['pixel_format']},"
        "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
        "-c:v",
        profile["encoder"],
        "-threads",
        str(threads),
        *settings,
        "-color_range",
        "tv",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        str(output),
    ]
