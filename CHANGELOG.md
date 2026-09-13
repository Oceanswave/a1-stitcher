# Changelog

## 0.7.0

- Add exposure-midpoint synchronization through explicitly refitted schema-2
  calibration. Check frame-zero anchoring, cadence, durations and coverage;
  preserve nominal calibration defaults and prevent silent clock downgrade.
- Add camera/accessory-bound native visibility masks for housing/guard exclusion,
  alternate-lens replacement and uncovered-region failure on CPU and Metal.
- Add `mask-template`, `mask-preview` and `stitch --occlusion-profile`, including
  batch paths, complete profile receipts and reuse identity.
- Document Studio observations, mixed reference residuals, two matched moving
  comparisons and the limits of authored masks versus automatic propeller removal.

## 0.6.0

- Add experimental 33-sample quaternion rolling-shutter trajectories on CPU
  and Metal, including overlap analysis. `--rolling-shutter-model trajectory`
  enables it; mixed real-footage results keep `velocity` as the default.
- Share an explicit source-frame heading across exports, defaulting to original
  frame zero. `--heading-reference-frame -1` restores clip-start heading.
- Decode observed exposure telemetry in `inspect` without changing the fitted
  frame clock or inventing shutter-edge synchronization.
- Remove whole-flight column copies from repeated gyro queries and cache bounded
  anchor corrections. Query partition/order does not change orientation results.
- Add ground-truth changing-motion, heading continuity, malformed telemetry and
  expanded CPU/Metal parity coverage. Document Studio observations, measured
  improvements, mixed results and remaining unsupported functionality.

See [0.6 qualification](docs/quality-v0.6.md).

## 0.5.0

- Default to 8K/native lens decoding and a 16-bit image pipeline with 10-bit HEVC.
  Add 10-bit ProRes 422 HQ MOV; retain explicit H.264 reviews.
- Add an independent Swift/Metal renderer with automatic preflight selection,
  CPU fallback receipts and explicit backend controls. Package native source.
- Add per-unit rigid gyro calibration, held-out/transfer checks and optional
  raw-gyro interpolation anchored to recorded attitude. Keep it experimental.
- Prevent cubic interpolation from mixing black border pixels into valid lens data.
- Extend codec verification, batch gyro-profile path handling, synthetic tests
  and the discoverable skill's complete options/reference documentation.
- Write explicit limited-range BT.709 ProRes container metadata for FFmpeg 6.1
  compatibility; reject missing or conflicting color descriptions.
- Run Python 3.12/3.13 CI on the dedicated Rockybot Linux runner, retaining
  separate full Metal testing on macOS before release.
- Preserve original files, no-overwrite outputs, GPX sidecars, calibration boundaries
  and the distinction between technical verification and perceptual review.

## 0.4.0

Export recorded flight tracks with `a1-stitch gpx` or `stitch --export-gpx`
(also `export_gpx: true` in batch jobs). Read indexed binary GPS record 7 without
Studio, calibration or video decoding for standalone extraction. Write GPX 1.1
positions, UTC timestamps and camera-reported elevation, with speed/course
extensions. Preserve gaps, reject unsupported/corrupt layouts, omit void fixes
and invalid positions, and retain sample counts and checksums in receipts.

GPX covers the entire source recording, including when the video is trimmed.
Altitude's vertical datum and precise GPS-to-video clock alignment remain
unqualified. No interpolated positions, assumed 3D fix, or guessed flight path.
Add synthetic parser, CLI, no-clobber, rollback and combined render/resume tests.

## 0.3.0

Fix false color bands revealed by matching Studio reference frames: stop
extrapolating overlap color correction into the wider sphere and across large
unsupported arcs. Skip projection and interpolation for lens samples with zero
output weight. Add experimental `--seam adaptive` with closed periodic seam
selection, bounded placement and limited temporal movement; keep `flow` default.
Decode both lens tracks through one reader, validate matching track start times,
and test exact original-frame pairing.

Add `a1-stitch compare` for explicitly mapped reference frames, full-sphere PNGs,
global alignment, geometry diagnostics and a local review page. Preserve the
unaligned candidate and report alignment changes so a per-frame fit cannot be
mistaken for stabilization acceptance. Add synthetic regression, correspondence,
closed-path optimality, motion-bound and complete CLI job tests.

## 0.2.0

Reduce seam ghosting through confidence-gated bidirectional optical flow and a
narrow detail transition. Add bounded, spatially smooth local lens color matching
with gradual temporal adaptation, while retaining original-resolution sampling.
Correct native sensor-row capture timing using embedded readout duration and
frame-local recorded angular velocity. Add `--seam flow|feather` and
`--rolling-shutter auto|off`, recipe/receipt evidence, and synthetic quality tests.
Document real-frame holdouts and the remaining occlusion/vibration/camera-removal
limits. The new quality defaults have additional CPU cost.

## 0.1.0

Initial alpha release: indexed INSV trailer reader, per-lens MEI projection,
reference-based per-camera calibration, recorded-attitude stitching, standard
spherical MP4 metadata, full output verification, reproducible receipts, safe
completed-job reuse, sequential batches, and a discoverable agent skill.

The renderer uses bounded image strips and process deadlines. Image-quality
qualification remains incomplete for rapid motion, rolling shutter, near seams,
camera/propeller removal, higher bit depth and other camera units.
