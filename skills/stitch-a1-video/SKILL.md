---
name: stitch-a1-video
description: Prepare Antigravity A1 INSV originals as stabilized 360 spheres with the a1-stitch CLI, including original-only setup, default pilot-follow playback, 16-bit panorama TIFFs, 8K/10-bit output, Metal acceleration, image/gyro synchronization, reviewed obstruction proposals, multiscale seams and GPX tracks. Use for A1 ingest, source-matched quality comparisons and repeatable batch preparation; retain the user's chosen editor for creative finishing.
---

# Prepare A1 footage

Use `a1-stitch` for original-source preparation. JSON goes to stdout and
progress/errors to stderr. It produces full spheres, guided view paths, RGB16 TIFFs, GPS sidecars and receipts;
it does not assemble a finished film. **This skill describes the 0.9.0 command set.**
Check `a1-stitch --version` and `a1-stitch stitch --help` before using new flags;
an older installed CLI must be updated from the public repository or a checked
local build. Never silently substitute another application named Antigravity.

Read [the options reference](references/options.md) when choosing encodes,
GPU/CPU operation, raw-gyro experiments, batch fields, or director integration.
The source is `https://github.com/Oceanswave/a1-stitcher`; a checkout can use its
`.venv/bin/a1-stitch`. Run `a1-stitch doctor` and inspect the actual source.

## Default to finishing quality

The defaults are **8192×4096, native lens resolution, 16-bit image processing,
10-bit HEVC MP4, flow seams, embedded frame orientation, pilot-follow companions and automatic
Metal selection on supported Macs**. CPU remains available with the same
geometry. Auto fallback and the actual backend are recorded; an explicit Metal
request fails if unavailable. HEVC encoding requires FFmpeg's `libx265`.

```sh
a1-stitch stitch SOURCE.insv \
  --first-frame FIRST --frames COUNT --output NEW_SPHERE.mp4 --dry-run
a1-stitch stitch SOURCE.insv \
  --first-frame FIRST --frames COUNT --output NEW_SPHERE.mp4
```

Frame zero and all ranges refer to the original; COUNT is a frame count. Retain
useful handles. Use `--encoding prores --output NEW_SPHERE.mov` for a ProRes
422 HQ intermediate. Use the explicit smaller H.264 settings in the reference
for previews; never substitute preview media for a finishing source.

The tested inputs remain **8-bit full-range SDR BT.709**. Higher precision reduces
additional rounding; it does not add captured detail or dynamic range. Log/HDR
inputs are rejected. Do not apply a guessed iLog/D-Log LUT. Output is limited-range
SDR BT.709; final matching/grading stays in the existing Resolve/Fusion workflow.

## Default original-only setup and pilot view

Omit `--calibration` to use embedded lens geometry, original overlap alignment
and record-32 camera orientation. No Studio export, SDK or manual calibration
step is required on supported originals. Automatic video setup needs at least
two consistent overlap fits; poor texture, unsupported view categories and
uncovered/gapped times fail explicitly. Do not invent or borrow a profile to
bypass a failure. An INSV suffix does not prove compatibility.

`--view pilot` is the default, including when an explicit calibration is supplied.
Keep `OUTPUT.viewport.json`, `OUTPUT.view.html` and the receipt with the video.
Run `a1-stitch view OUTPUT.mp4` for checksum-verified local guided playback.
The full sphere remains stabilized; only the viewer follows the pilot. Ordinary
360 players do not automatically read this path. Use `--view fixed` to opt out.
Use that opt-out together with `--no-stabilization` for a diagnostic raw pose.

The path has output-relative times and XYZW camera-to-sphere quaternions. Inspect
pilot direction on real moving footage; recorded zoom and proprietary tracking
modes remain unqualified. The player starts at 90° horizontal FOV and allows
free look/zoom and a smooth return to pilot follow. JSON-only edits do not update
the embedded HTML path and invalidate receipt verification.

Original-only mode records schema-4 geometry in the receipt and disables raw
sensor-row corrections. Raw gyro and exposure/image timing require an explicit
schema 1–3 sensor calibration. Do not claim those corrections remain active in
automatic mode or that frame orientation equals proprietary FlowState.

## 360 still photos

```sh
a1-stitch photo SOURCE.insp --output NEW_PANORAMA.tiff
a1-stitch verify-photo NEW_PANORAMA.tiff --receipt NEW_PANORAMA.tiff.receipt.json
```

This stitches supported JPEG-based A1 INSP originals to native-width, full-sphere
RGB16 TIFFs with lossless Deflate, GPano XMP in TIFF tag 700, full/cropped panorama
dimensions and zero crop offsets. An available ICC is preserved. Do not assign a
guessed color profile, claim RAW development, or call an 8-bit source 16-bit capture.
EXIF/GPS and the proprietary trailer stay in the original; DNG is unsupported.
Use `--width` for smaller review images; never promote them as native finishing
files. Inspect horizon, seams, flare and near objects separately from decode/tag
checks. Panorama-aware TIFF support depends on the receiving application.

## Inspect and optionally calibrate the sensor path

Run `a1-stitch inspect SOURCE.insv --output NEW_REPORT.json`. Confirm A1 identity,
two square lens tracks, timing and embedded calibration. An INSV suffix or 2:1
raster alone does not prove stitching. Preserve originals and private profiles.
Reports may reveal paths; GPX reveals real locations even with paths redacted.

When using advanced sensor processing, an existing calibration must match the original's embedded-lens fingerprint.
Do not borrow another camera's mounting transform. New calibration needs a full
sphere reference from the same original with a documented first source frame:

```sh
a1-stitch calibrate SOURCE.insv --reference STUDIO_SPHERE.mp4 \
  --first-source-frame FIRST_ORIGINAL_FRAME \
  --samples 0,15,30,60,120,240,480 --holdouts 600,900 \
  --output NEW_CALIBRATION.json --evidence-dir NEW_EVIDENCE_DIRECTORY
```

Adjust sample/holdout indices to the reference interval. Choose texture and varied
tilt and inspect held-out comparisons. A flat reframe is not a valid reference.
A missing reference does not block original-only export. Establish this dependency
only for the advanced sensor path. Existing authorization governs vendor exports.

## Motion and seam choices

With an explicit schema 1–3 calibration, recorded attitude is the baseline. `gyro-calibrate` fits a per-unit rigid
sensor rotation, timing offset and bias, with held-out blocks and a different
recording for transfer validation. `--gyro-profile` integrates raw gyro between
recorded attitude anchors (`--gyro-anchor-seconds 0.1` by default in this
optional mode; 0.02 uses every recorded anchor). This bounds drift; it does **not** prove high-frequency
sensor-to-image timing. Read the options reference and compare actual moving
shots before choosing it. Do not enable it merely because the sample rate is higher.

`--seam flow` rejects unreliable correspondences and confines color matching to
measured overlap. `--seam adaptive` is an optional bounded moving seam, not camera
removal. With an explicit sensor calibration, `--rolling-shutter auto` uses native
sensor rows and embedded readout duration. Keep the proven `--rolling-shutter-model velocity` default for ordinary
preparation. The experimental `trajectory` option uses 33 quaternion samples
through the scan. It improves synthetic changing-motion recovery but produced
mixed real-footage results, including a worse gyro transfer diagnostic. The
optional gyro profile can feed either row model. Sensor timing and sampling still
limit accuracy; this does not deblur exposure or reconstruct missing detail.

`--heading-reference-frame 0` keeps a consistent panorama heading across ranges
from one original. Use the same covered reference frame for all chunks; `-1`
uses the selected clip start as in 0.5. This is not calibrated compass north.
For exposure-aware sync, create a **new** calibration with
`calibrate --frame-clock exposure`. Its schema-2 clock is applied automatically;
never add a guessed shutter offset or relabel an old profile. Short moving tests
improved but reference holdouts were mixed, so nominal calibration stays default.
A lower seam residual or newer algorithm alone does not establish better image quality.

For camera/guard intrusion, use `mask-template`, author observed native-image
exclusions, then `mask-preview` before supplying `--occlusion-profile`. Read
[exposure and visibility profiles](references/options.md#exposure-and-visibility-profiles)
for coordinate conventions and limits. The masks are bound to lens identity and
recorded guard configuration. They use actual alternate-lens pixels and fail
when both lenses are blocked; they do not detect every blade or invent hidden
surfaces. Tight measured outlines preserve more overlap than broad cutoffs.
Review moving seams, flare and blade blur before accepting the profile.

For image-based timing, use `sync-calibrate` with the base nominal/exposure
calibration and gyro profile. Inspect its JSON status: rejection produces evidence
but no usable profile. Schema 3 preserves the fitted capture mode, gyro fingerprint, anchor
spacing and trajectory row model. A successful local holdout is not transfer
qualification. Keep unsuccessful experiments out of defaults.

`mask-propose` generates native overlay sheets and a schema-2 proposal from
multiple frames. Inspect/refine the exclusions, then use `mask-approve` with
actual review notes. Empty or unreviewed proposals cannot render. Do not approve
image rims, static scene objects or unsupported guesses about blades. Forced
replacement checks alternate clipping/contrast and fails when neither view is
usable. This remains incomplete object detection, not reconstruction.

`--seam multiband` is an opt-in three-band overlap blend with bounded gain changes;
it retains native high-frequency detail and does not average pixels over time.
Compare it on moving seams before selecting it. Detailed bounds and examples are
in [the new quality tools](references/options.md#image-timing-masks-and-continuous-comparisons).

## Flight profiles and repeated jobs

`a1-stitch gpx SOURCE.insv --output NEW_FLIGHT.gpx` needs no calibration or FFmpeg.
Add `--export-gpx` to stitching for `OUTPUT.mp4.gpx` or `OUTPUT.mov.gpx` with a
checksum in the video receipt. This is the **entire source recording's** GPS,
not the selected clip and not necessarily the complete multi-file flight.

Missing/invalid GPS is an error, not an invitation to invent positions. Void fixes
and gaps split segments. Altitude datum and precise UTC/video synchronization
remain unqualified. Do not label altitude as AGL, takeoff-relative or surveyed MSL.

Use `--resume` to verify/reuse an identical completed job. It does not continue
partial encodes. Source, profile, processing/version changes invalidate reuse.
Combined resume verifies video, guided companions and requested GPX. `--keep-work` retains diagnostic files.
For a stale lock, establish that its owner is gone before removing it.

## Review and hand off

Use `a1-stitch benchmark` for contiguous 20–30-second Studio comparisons with
six fixed views and one initial alignment. Automated all-frame coverage is not
human playback acceptance. Use `a1-stitch compare` for sampled geometric detail. Per-frame global
alignment exposes stitching differences but can hide horizon shake; inspect
original orientation and moving reframes too. Read source lenses before assuming
a dark region is a propeller or a geometry problem.

Run `a1-stitch verify NEW_SPHERE.mp4 --receipt NEW_SPHERE.mp4.receipt.json` and check
source mapping, dimensions, codec, color, frame count, calibration and warnings.
Full decode/checksum success is separate from perceptual acceptance. Review the
entire selected shot in motion for horizon drift, abrupt rotation, seams and
vehicle shape. Record actual coverage. Keep unreviewed outputs out of a library's
verified-master category; camera visibility, occlusion and residual vibration
remain limits.

Retain the original-frame range, receipt, GPX association and color profile when
handing media to the existing editor. In a workspace with `scripts/director.py`,
the reference documents preparation, registration and Resolve-select handoff.
Keep recorded-attitude correction separate from creative camera movement. For a
new film, check prior-event usage: a new crop, grade or timestamp does not establish
a fresh event. Respect the user's project-specific reuse exclusions.
