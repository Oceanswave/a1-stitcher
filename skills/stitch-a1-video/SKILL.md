---
name: stitch-a1-video
description: Inspect, calibrate, and stitch Antigravity A1 INSV originals into stabilized equirectangular MP4s with the a1-stitch CLI. Use for A1 ingest, repeatable 360 preparation, batch conversion, or troubleshooting A1 metadata and stabilization; preserve the user's chosen editor for creative finishing.
---

# Prepare A1 footage

Use `a1-stitch` for original-source preparation. It runs locally and returns JSON
on stdout, with progress/errors on stderr. It produces complete spheres and
receipts; it does not assemble a finished film. Version 0.3.0 includes checked optical
flow, local lens color balance, native-row rolling-shutter correction, experimental
adaptive seams and mapped Studio comparisons. Image
quality is still alpha around occlusion, severe parallax, vibration and camera
visibility; a valid encode does not establish perceptual acceptance.

## Locate and inspect

Check `command -v a1-stitch`, then `a1-stitch doctor`. If absent, use the install
instructions in the public repository: `https://github.com/Oceanswave/a1-stitcher`.
A source checkout can run `.venv/bin/a1-stitch` after installing the package.
Do not silently choose a different application named Antigravity.

Run `a1-stitch inspect SOURCE.insv --output NEW_REPORT.json`. Confirm the actual
camera, two square lens tracks, frame rate, calibration and attitude coverage.
An INSV suffix or a 2:1 image alone does not prove that footage is stitched.
Preserve originals. Local reports/receipts may contain filenames and absolute
paths; review/redact them before any authorized sharing.

## Choose calibration

Use an existing profile only when the tool verifies its embedded-lens fingerprint
against this original. Do not copy another camera owner's mounting transform.
If no profile exists, first check for a previously prepared full equirectangular
reference from the same original with a documented first source frame. Do not
use a flat reframed export as calibration input.

```sh
a1-stitch calibrate SOURCE.insv --reference SPHERE.mp4 \
  --first-source-frame FIRST_ORIGINAL_FRAME \
  --samples 0,15,30,60,120,240,480 --holdouts 600,900 \
  --output NEW_CALIBRATION.json --evidence-dir NEW_EVIDENCE_DIRECTORY
```

Adjust all sample/holdout indices to the real reference interval. They are
reference frames; `--first-source-frame` maps its frame zero into the original.
Use texture and varied tilt, and inspect holdout errors and paired evidence.
If the reference is unavailable, report that one-time calibration dependency and
continue independent inspection/scouting; do not fabricate a profile or claim
SDK compatibility. Existing user authorization governs any vendor export step.

## Render selected ranges

```sh
a1-stitch stitch SOURCE.insv --calibration CALIBRATION.json \
  --first-frame FIRST --frames COUNT --output NEW_SPHERE.mp4 --dry-run
a1-stitch stitch SOURCE.insv --calibration CALIBRATION.json \
  --first-frame FIRST --frames COUNT --output NEW_SPHERE.mp4
```

Select original ranges with useful handles. The first frame is zero-based and
`--frames` is a count. Defaults create a 2048×1024 review sphere; retain appropriate
lens decode resolution for higher-resolution work (`--width 4096 --lens-width
3840`, for example). Output is currently 8-bit SDR BT.709. The CLI rejects
unqualified profiles instead of applying a guessed I-Log/D-Log LUT.

Defaults are `--seam flow --rolling-shutter auto`. Flow aligns the shared lens
area and rejects unreliable correspondences. Color balance reduces the brighter
local mismatch without amplifying the cleaner lens; it is not a grading LUT.
Row correction uses each native sensor row and the embedded readout duration,
not the output sphere's row. Use `--seam feather --rolling-shutter off` for a
controlled legacy comparison or when the newer corrections are unsuitable.
Check seam diagnostics and the actual shot, including temporal color changes;
trusted-overlap residuals are not whole-image quality scores. CPU cost is higher.

For difficult overlap, compare `--seam adaptive` with the default `flow`. Adaptive
placement is bounded and moves gradually; it does not identify camera bodies or
reconstruct occluded detail. Do not select it solely because it is newer.

For repeated jobs, use `--resume`: it reuses only an identical completed output
with a valid receipt/checksum. It does not continue partial encodes. A stale lock
requires checking its PID before removing it. `--keep-work` retains diagnostic
files for failed jobs. A JSON batch manifest supports sequential jobs and
resolves relative paths against its own directory; read the repository README
for its schema instead of inventing fields.

## Verify and hand off

When a full Studio reference exists, use matching source moments to expose
differences. `a1-stitch compare CANDIDATE.mp4 --reference STUDIO.mp4
--reference-first-frame OFFSET --samples 0,15,30,60 --output-dir NEW_REVIEW`
maps candidate frame zero to reference frame OFFSET. Sample indices belong to
the candidate; choose indices within both videos. Both require the same frame
rate and full-sphere content. Read the generated JSON and `review.html`.
The aligned view removes only global rotation, with no color fit or local warp.
Inspect the unaligned candidate and alignment changes too: per-frame alignment
can hide horizon shake. Neither inlier geometry scores nor selected stills cover
unmatched pixels or full motion. If a color band appears, compare original lens
pixels before assuming that it is a propeller or a stitching geometry problem.

Run `a1-stitch verify NEW_SPHERE.mp4 --receipt NEW_SPHERE.mp4.receipt.json`.
Check the receipt's source range, profile, frame count, calibration and warnings.
Full decoding, metadata validity and checksum reuse are technical checks; they
are not perceptual acceptance. Review the selected shot in motion, including
horizon drift, sudden rotation, seams through nearby subjects and vehicle shape.
Record what was actually reviewed. Keep unqualified outputs out of a library's
verified-master category.

Then pass the sphere to the user's existing 360 reframe/editor workflow. Keep
creative camera motion separate from recorded-attitude correction and color
finishing. A new view of an old event does not establish fresh footage for a new
film; retain source/event mappings and any project-specific reuse exclusions.
