"""A1 INSP to losslessly compressed RGB16 TIFF with Photo Sphere XMP."""

import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import cv2
import numpy as np
import tifffile
from PIL import Image

from . import __version__
from .automatic import fit_overlap
from .calibration import lens_fingerprint, load_calibration
from .errors import StitchError
from .insv import InsvReader
from .metal import select_backend
from .modes import require_recording_mode
from .projection import TiledStitcher, lenses_from_metadata
from .storage import (
    digest,
    fingerprint,
    identity,
    load_json,
    output_lock,
    publish_file,
    write_new_json,
)
from .viewpoint import Viewpoint

GPANO = "http://ns.google.com/photos/1.0/panorama/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def panorama_xmp(width, height):
    ET.register_namespace("x", "adobe:ns:meta/")
    ET.register_namespace("rdf", RDF)
    ET.register_namespace("GPano", GPANO)
    root = ET.Element("{adobe:ns:meta/}xmpmeta")
    desc = ET.SubElement(
        ET.SubElement(root, f"{{{RDF}}}RDF"), f"{{{RDF}}}Description", {f"{{{RDF}}}about": ""}
    )
    values = dict(
        ProjectionType="equirectangular",
        UsePanoramaViewer="True",
        StitchingSoftware=f"A1 Stitcher {__version__}",
        FullPanoWidthPixels=width,
        FullPanoHeightPixels=height,
        CroppedAreaImageWidthPixels=width,
        CroppedAreaImageHeightPixels=height,
        CroppedAreaLeftPixels=0,
        CroppedAreaTopPixels=0,
    )
    for key, value in values.items():
        ET.SubElement(desc, f"{{{GPANO}}}{key}").text = str(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def verify_photo(path, receipt=None):
    with tifffile.TiffFile(path) as image:
        if len(image.pages) != 1:
            raise StitchError("Expected one full-sphere TIFF image")
        page = image.pages[0]
        if (
            page.dtype != np.uint16
            or page.shape != (page.imagelength, page.imagewidth, 3)
            or page.photometric != 2
        ):
            raise StitchError("Expected a 16-bit RGB TIFF")
        if page.imagewidth != page.imagelength * 2:
            raise StitchError("TIFF is not a complete 2:1 sphere")
        if 700 not in page.tags:
            raise StitchError("TIFF lacks Photo Sphere XMP")
        try:
            xml = ET.fromstring(page.tags[700].value)
            values = {
                e.tag.split("}")[-1]: e.text
                for e in xml.iter()
                if e.tag.startswith("{" + GPANO + "}")
            }
            expected = dict(
                ProjectionType="equirectangular",
                UsePanoramaViewer="True",
                FullPanoWidthPixels=str(page.imagewidth),
                FullPanoHeightPixels=str(page.imagelength),
                CroppedAreaImageWidthPixels=str(page.imagewidth),
                CroppedAreaImageHeightPixels=str(page.imagelength),
                CroppedAreaLeftPixels="0",
                CroppedAreaTopPixels="0",
            )
            if any(values.get(k) != v for k, v in expected.items()):
                raise StitchError("TIFF panorama metadata disagrees with its pixels")
        except ET.ParseError as exc:
            raise StitchError("Malformed TIFF panorama metadata") from exc
        pixels = page.asarray()  # Actually decompress the complete image.
        import hashlib

        pixel_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
        result = dict(
            width=page.imagewidth,
            height=page.imagelength,
            bits_per_sample=16,
            projection="equirectangular",
            compression=page.compression.name,
            full_decode=True,
            pixel_sha256=pixel_sha,
            output_sha256=digest(path),
        )
    if receipt:
        saved = load_json(receipt)
        if (
            saved.get("output_sha256") != result["output_sha256"]
            or saved.get("verification", {}).get("pixel_sha256") != pixel_sha
        ):
            raise StitchError("TIFF checksum differs from receipt")
    return result


def export_photo(
    source,
    output,
    *,
    calibration=None,
    width=0,
    backend="auto",
    seam="flow",
    resume=False,
    dry_run=False,
):
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    receipt = Path(str(output) + ".receipt.json")
    if output.suffix.lower() not in [".tif", ".tiff"]:
        raise StitchError("Photo export requires a .tif or .tiff output")
    protected = {source}
    if calibration:
        protected.add(Path(calibration).resolve(strict=True))
    if output.resolve() in protected or receipt.resolve() in protected:
        raise StitchError("Photo output would overwrite an input")
    if (
        type(width) is not int
        or width < 0
        or (width and (width < 64 or width > 16384 or width % 4))
    ):
        raise StitchError("Photo width must be 0 or a multiple of 4 between 64 and 16384")
    if seam not in ["flow", "multiband", "feather"]:
        raise StitchError("Photo seam must be flow, multiband or feather")
    reader = InsvReader(source)
    meta = reader.metadata()
    if meta.get("camera_type") != "Antigravity A1" or meta.get("gamma_mode") not in [None, ""]:
        raise StitchError(
            "Expected a supported A1 rendered INSP photo; RAW/log development is not implemented"
        )
    mode = require_recording_mode(meta, "photo")
    view = Viewpoint(reader, photo=True)
    before = identity(source)
    with Image.open(source) as photo:
        if (
            photo.format != "JPEG"
            or photo.mode != "RGB"
            or photo.width != photo.height * 2
            or photo.width > 16384
        ):
            raise StitchError(
                "Expected a bounded JPEG-based two-lens A1 INSP; DNG is not yet supported"
            )
        if photo.getexif().get(274, 1) != 1:
            raise StitchError("Unexpected photo pixel orientation")
        if meta.get("dimension") != dict(x=photo.width, y=photo.height):
            raise StitchError("Photo dimensions disagree with the camera metadata")
        if width > photo.width:
            raise StitchError("Photo output width exceeds source resolution")
        width = width or photo.width
        icc = photo.info.get("icc_profile")
        pixels = np.asarray(photo)[:, :, ::-1].copy()
    backend_info = select_backend(backend)
    recipe = dict(
        kind="a1-insp-rgb16-v1",
        recording_mode=mode,
        package_version=__version__,
        source_identity=before,
        width=width,
        seam=seam,
        backend=backend_info,
        lens_fingerprint=lens_fingerprint(meta),
        calibration=load_calibration(calibration, meta) if calibration else None,
        orientation=view.report(),
        color="camera-rendered RGB; no LUT or assumed RAW/HDR development",
        icc_preserved=bool(icc),
        source_precision_bits=8,
        output_precision_bits=16,
    )
    # Include all processing sources in resume identity, including the renderer.
    recipe["implementation"] = fingerprint(
        {
            str(p.relative_to(Path(__file__).parent)): digest(p)
            for p in sorted(Path(__file__).parent.rglob("*"))
            if p.suffix in [".py", ".metal", ".swift"]
        }
    )
    recipe_sha = fingerprint(recipe)
    if dry_run:
        return dict(status="planned", output=str(output), recipe=recipe)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        if any(p.exists() or p.is_symlink() for p in [output, receipt]):
            if not resume or not all(p.is_file() and not p.is_symlink() for p in [output, receipt]):
                raise StitchError(
                    "Photo output/receipt already exists; use --resume for a completed identical job"
                )
            saved = load_json(receipt)
            if saved.get("recipe_sha256") != recipe_sha:
                raise StitchError("Photo source or processing settings changed")
            return dict(
                status="reused",
                output=str(output),
                receipt=str(receipt),
                verification=verify_photo(output, receipt),
            )
        native = pixels.shape[0]
        lenses = lenses_from_metadata(meta, native)
        frames = [
            pixels[:, :native].astype(np.uint16) * 257,
            pixels[:, native:].astype(np.uint16) * 257,
        ]
        if recipe["calibration"]:
            relative = np.array(recipe["calibration"]["rotation_lens1_to_lens0"])
            overlap = dict(method="explicit-profile")
        else:
            fit_width = min(native, 1920)
            pair = [
                cv2.resize(f, (fit_width, fit_width))
                for f in [pixels[:, :native], pixels[:, native:]]
            ]
            relative, overlap = fit_overlap([pair], lenses_from_metadata(meta, fit_width))
        renderer = TiledStitcher
        if backend_info["name"] == "metal":
            from .metal import MetalStitcher

            renderer = MetalStitcher
        stitcher = renderer(lenses, relative, width, seam=seam)
        try:
            sphere, missing = stitcher.stitch(frames, view.camera[0].as_matrix().T)
        finally:
            if hasattr(stitcher, "close"):
                stitcher.close()
        if missing > 0.001:
            raise StitchError("Photo geometry leaves uncovered sphere pixels")
        rgb = np.ascontiguousarray(sphere[:, :, ::-1])
        with tempfile.TemporaryDirectory(prefix=".a1-photo-", dir=output.parent) as folder:
            ready = Path(folder) / "sphere.tiff"
            xmp = panorama_xmp(width, width // 2)
            tags = [(700, "B", len(xmp), xmp, False)]
            if icc:
                tags.append((34675, "B", len(icc), icc, False))
            tifffile.imwrite(
                ready,
                rgb,
                photometric="rgb",
                compression="deflate",
                metadata=None,
                software=f"A1 Stitcher {__version__}",
                extratags=tags,
            )
            checked = verify_photo(ready)
            import hashlib

            if checked["pixel_sha256"] != hashlib.sha256(rgb.tobytes()).hexdigest():
                raise StitchError("TIFF encoding changed the rendered pixels")
            if identity(source) != before:
                raise StitchError("Original changed during photo export")
            report = dict(
                schema_version=1,
                status="complete",
                recipe=recipe,
                recipe_sha256=recipe_sha,
                output_sha256=checked["output_sha256"],
                verification=checked,
                overlap=overlap,
                max_uncovered_fraction=missing,
                quality_status="experimental; inspected geometry is separate from decode validation",
                limitations=[
                    "RGB16 preserves processing precision; the INSP source is 8-bit",
                    "Source EXIF/GPS and proprietary trailer remain in the original; only available ICC and panorama XMP are embedded",
                ],
            )
            publish_file(ready, output)
            try:
                write_new_json(receipt, report)
            except BaseException:
                if output.exists() and output.stat().st_ino == ready.stat().st_ino:
                    output.unlink()
                raise
    return dict(status="created", output=str(output), receipt=str(receipt), verification=checked)
