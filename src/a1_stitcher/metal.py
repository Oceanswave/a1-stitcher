"""Optional independent Metal renderer; no vendor runtime or model dependencies."""

import ctypes
import platform
import shutil
import tempfile
from pathlib import Path

import numpy as np

from .errors import StitchError
from .process import run
from .projection import TiledStitcher

_RUNTIME = None


def runtime():
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME[1]
    if platform.system() != "Darwin" or not shutil.which("swiftc"):
        raise StitchError("Metal requires macOS, a Metal GPU and the Swift command line tools")
    folder = tempfile.TemporaryDirectory(prefix="a1-metal-")
    native = Path(__file__).parent / "native"
    library = Path(folder.name) / "renderer.dylib"
    try:
        run(
            [
                shutil.which("swiftc"),
                "-O",
                "-emit-library",
                "-module-cache-path",
                str(Path(folder.name) / "modules"),
                str(native / "bridge.swift"),
                "-o",
                str(library),
            ],
            timeout=120,
        )
        lib = ctypes.CDLL(str(library))
        pointer = ctypes.c_void_p
        lib.a1_create.argtypes = [ctypes.c_char_p, pointer, ctypes.c_int32]
        lib.a1_create.restype = pointer
        lib.a1_destroy.argtypes = [pointer]
        lib.a1_destroy.restype = None
        lib.a1_device_name.argtypes = [pointer, pointer, ctypes.c_int32]
        lib.a1_device_name.restype = None
        lib.a1_render.argtypes = [
            pointer,
            pointer,
            pointer,
            pointer,
            ctypes.c_int64,
            ctypes.c_int32,
            ctypes.c_int32,
            pointer,
            pointer,
            ctypes.c_int32,
        ]
        lib.a1_render.restype = ctypes.c_int32
        _RUNTIME = (folder, lib)
        return lib
    except Exception:
        folder.cleanup()
        raise


class MetalStitcher(TiledStitcher):
    """Serial renderer with CPU seam analysis and explicit failure, never silent fallback."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lib = runtime()
        error = ctypes.create_string_buffer(4096)
        source = (Path(__file__).parent / "native" / "stitch.metal").read_bytes()
        self.handle = self.lib.a1_create(source, error, len(error))
        if not self.handle:
            raise StitchError(f"Cannot initialize Metal: {error.value.decode(errors='replace')}")
        self.gpu_seconds = 0.0

    def close(self):
        if getattr(self, "handle", None):
            self.lib.a1_destroy(self.handle)
            self.handle = None

    def __del__(self):
        self.close()

    def stitch(self, frames, world_to_lens, angular_velocity=None):
        if not self.handle:
            raise StitchError("Metal renderer is closed")
        if len(frames) != 2 or frames[0].dtype not in (np.uint8, np.uint16):
            raise StitchError("Expected two uint8 or uint16 lens images")
        if any(
            f.shape != (lens["width"], lens["width"], 3) or f.dtype != frames[0].dtype
            for f, lens in zip(frames, self.lenses)
        ):
            raise StitchError("Lens image shape or precision differs from the calibration")
        rotation = np.asarray(world_to_lens, np.float32)
        velocity = (
            np.zeros(3, np.float32)
            if angular_velocity is None
            else np.asarray(angular_velocity, np.float32)
        )
        if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
            raise StitchError("World rotation must be a finite 3x3 matrix")
        if velocity.shape != (3,) or not np.isfinite(velocity).all():
            raise StitchError("Angular velocity must be a finite three-vector")
        p = np.zeros(52, np.float32)
        p[:3] = self.width, frames[0].dtype == np.uint16, self.seam is not None
        p[8:17] = rotation.ravel()
        p[17:26] = self.relative.ravel()
        p[26:30] = [*velocity, self.readout_seconds]
        for i, lens in enumerate(self.lenses):
            k = lens["K"]
            p[30 + i * 11 : 41 + i * 11] = [
                lens["xi"],
                k[0, 0],
                k[1, 1],
                k[0, 2],
                k[1, 2],
                *lens["distortion"],
                lens["width"],
            ]
        analysis = np.zeros(1, np.float32)
        if self.seam is not None:
            s = self.seam
            s.prepare(frames, angular_velocity, self.readout_seconds)
            p[3:5] = s.width, s.height
            ratio = (
                s.log_ratio if s.log_ratio is not None else np.zeros((1, s.width, 3), np.float32)
            )
            path = s.path_latitude if s.path_latitude is not None else np.zeros(1, np.float32)
            p[5] = s.path_latitude.shape[1] if s.path_latitude is not None else 0
            analysis = np.concatenate(
                [v.ravel() for v in [*s.flows, *s.confidence, ratio, path]]
            ).astype(np.float32)
        arrays = [np.ascontiguousarray(f) for f in frames] + [p, analysis, np.zeros(1, np.float32)]
        pointers = (ctypes.c_void_p * 5)(*[v.ctypes.data for v in arrays])
        sizes = (ctypes.c_int64 * 5)(*[v.nbytes for v in arrays])
        output = np.empty((self.height, self.width, 3), frames[0].dtype)
        metrics = np.zeros(2, np.float64)
        error = ctypes.create_string_buffer(4096)
        code = self.lib.a1_render(
            self.handle,
            pointers,
            sizes,
            output.ctypes.data,
            output.nbytes,
            self.width,
            self.height,
            metrics.ctypes.data,
            error,
            len(error),
        )
        if code:
            self.close()
            raise StitchError(
                f"Metal render failed ({code}): {error.value.decode(errors='replace')}"
            )
        self.gpu_seconds += metrics[0]
        return output, metrics[1] / (self.width * self.height)


def select_backend(requested):
    """Preflight auto selection; actual backend and any fallback enter the receipt."""
    if requested == "cpu":
        return dict(name="cpu", reason="explicit CPU selection")
    if requested not in ("auto", "metal"):
        raise StitchError("Backend must be auto, cpu or metal")
    if requested == "auto" and (platform.system() != "Darwin" or not shutil.which("swiftc")):
        return dict(name="cpu", reason="Metal or Swift tools unavailable on this host")
    try:
        renderer = MetalStitcher([], np.eye(3), 64, seam="feather")
        try:
            name = ctypes.create_string_buffer(512)
            renderer.lib.a1_device_name(renderer.handle, name, len(name))
            return dict(
                name="metal",
                device=name.value.decode(errors="replace"),
                shader="independent-metal-v1",
            )
        finally:
            renderer.close()
    except (StitchError, OSError) as exc:
        if requested == "metal":
            raise
        return dict(name="cpu", reason=f"Metal preflight failed: {exc}")
