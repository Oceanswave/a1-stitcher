# Changelog

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
