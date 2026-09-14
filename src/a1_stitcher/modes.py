"""A1 recording-mode declarations, distinct from pixel and timing qualification.

These are wire-format identifiers, not a list of features sold for the A1.
Shared Studio metadata includes modes that are not documented A1 capabilities.
See docs/recording-modes.md for the evidence and current coverage.
"""

from .errors import StitchError

UAV_MODES = {
    0: "standard-video",
    1: "standard-photo",
    2: "timelapse",
    3: "hdr-video",
    4: "slow-motion",
    5: "hdr-photo",
    6: "burst-photo",
    7: "aeb-photo",
    8: "interval-photo",
    9: "stack-photo",
    10: "playback",
}
GROUP_MODES = {
    0: "standard-video",
    2: "timelapse",
    3: "standard-photo",
    4: "hdr-photo",
    5: "interval-photo",
    6: "hdr-video",
    7: "burst-photo",
    8: "timelapse",
    17: "slow-motion",
    28: "aeb-photo",
}


def recording_mode(metadata):
    declarations = {}
    for field, names in [("uav_camera_mode", UAV_MODES), ("file_group_type", GROUP_MODES)]:
        if field in metadata:
            value = metadata[field]
            if type(value) is not int or value < 0:
                raise StitchError(f"Invalid {field} recording-mode value")
            declarations[field] = dict(value=value, name=names.get(value, "unknown"))
    names = {d["name"] for d in declarations.values()}
    if "unknown" in names:
        mode = "unknown"
    elif len(names) > 1:
        mode = "conflicting"
    else:
        mode = next(iter(names), "unspecified")
    return dict(
        name=mode,
        declarations=declarations,
        status="requires-pixel-and-timing-checks"
        if mode in ["standard-video", "standard-photo", "unspecified"]
        else "not-yet-supported",
        qualification="Mode identifiers alone do not establish supported timing, color or image quality",
    )


def require_recording_mode(metadata, kind):
    report = recording_mode(metadata)
    mode = report["name"]
    if mode not in [f"standard-{kind}", "unspecified"]:
        if mode in ["timelapse", "slow-motion"]:
            reason = (
                "capture-to-playback timing and pilot/gyro synchronization are not yet qualified"
            )
        elif mode in ["hdr-photo", "aeb-photo", "burst-photo", "interval-photo", "stack-photo"]:
            reason = "grouped capture and exposure merging are not yet qualified"
        else:
            reason = "the declared recording mode is not qualified for this export"
        raise StitchError(f"A1 {mode}: {reason}; see docs/recording-modes.md")
    # Do not mistake a shared metadata enum for proof that the A1 offers HDR.
    # If an original declares it, require a qualified development path regardless.
    if (
        metadata.get("hdr_state", 0) != 0
        or metadata.get("hdr_mode", 0) not in [0, 1]
        or metadata.get("ultra_hdr_enabled", 0) != 0
        or metadata.get("video_bit_depth", 0) not in [0, 1]
    ):
        raise StitchError("Declared HDR or higher-bit-depth input requires a qualified color path")
    return report
