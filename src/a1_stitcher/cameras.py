"""Camera capabilities: an input contract is separate from qualified rendering."""

from dataclasses import dataclass

from .errors import StitchError
from .modes import require_recording_mode


@dataclass(frozen=True)
class CameraAdapter:
    name: str
    identifier: str
    sphere_export: bool
    gamma_modes: tuple
    audio_ingest: bool = False

    def require_sphere_export(self):
        if not self.sphere_export:
            raise StitchError(
                f"{self.name} sphere export is not qualified: sensor-to-lens orientation, "
                "image timing and moving seams require validation; use preflight for input checks"
            )

    def profile(self, info, metadata):
        from .audio import audio_profile
        from .media import lens_video_profile

        if metadata.get("camera_type") != self.name:
            raise StitchError("Camera adapter does not match source identity")
        if metadata.get("gamma_mode") not in self.gamma_modes:
            raise StitchError("Explicit camera gamma mode has not been qualified")
        if self.identifier == "x5-sdr-v1":
            # X5 uses the shared file-group declaration, not A1's UAV mode enum.
            if "uav_camera_mode" in metadata or metadata.get("file_group_type") != 0:
                raise StitchError("X5 preflight requires an explicit standard-video file group")
        mode = require_recording_mode(metadata, "video", camera=self.name)
        if not self.audio_ingest and any(s["codec_type"] == "audio" for s in info["streams"]):
            raise StitchError("Audio preservation is not implemented; refusing to silently drop it")
        result = lens_video_profile(info, metadata, mode)
        if self.audio_ingest:
            result["audio"] = audio_profile(info)
            result["video_start_seconds"] = next(
                s["start_time"] for s in info["streams"] if s["index"] == result["streams"][0]
            )
        return result


A1 = CameraAdapter("Antigravity A1", "a1-v1", True, (None, ""))
X5 = CameraAdapter("Insta360 X5", "x5-sdr-v1", False, ("standard",), True)
ADAPTERS = {adapter.name: adapter for adapter in (A1, X5)}


def camera_adapter(metadata):
    name = metadata.get("camera_type")
    try:
        return ADAPTERS[name]
    except (KeyError, TypeError) as exc:
        raise StitchError(
            f"Unsupported camera model: {name!r}; no model inferred from extension"
        ) from exc
