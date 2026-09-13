# Original-only preparation, pilot view and TIFF validation

This documents the implementation released as 0.9.0, including its development
qualification. The explicit sensor-calibration workflow from 0.8 remains available. These checks establish
specific behavior; they do not establish universal A1 firmware support or
Studio-equivalent image quality.

## Format evidence and automatic setup

Read-only inspection of local Studio readers identified the 120-byte record-32
layout, length-prefixed video header and WXYZ quaternion ordering. Independent
coordinate hypotheses were checked against original metadata, relative camera
motion, a separately reference-calibrated vertical and a stitched photo. No
vendor implementation or profile is included or required by the CLI.

Three original videos provided 10,840, 16,570 and 22,739 increasing view samples,
all category zero and without gaps over 250 ms. The sampled original-only vertical
agreed with the previously calibrated vertical to median/p95 0.60°/1.02° on the
forest recording. Absolute heading did not maintain a constant relationship to
the raw attitude stream; this is not calibrated north or proven drift-free yaw.

A fast-turn frame fit differed from two nearby fits by about 1.55°. The nearby
fits agreed within 0.045°. Automatic setup rejects the outlier and requires at
least two candidates plus a strict majority within 0.75°, rather than averaging
those incompatible results. Each fit also checks inlier count/fraction and p95
residual. Failure produces no completed media.

A 300-frame, 10.01-second original-only development export at 2048×1024 decoded
fully, had valid spherical/color tags and zero uncovered pixels. On the local
M1 Max, its receipt measured 39.18 seconds including automatic setup, rendering
and verification. This is a small H.264 review with 1920-pixel decoded lenses;
it is not native 8K throughput or a new CPU-versus-Metal speedup comparison.
Historical measured GPU speedups remain in [the 0.5 report](quality-v0.5.md).

## Pilot viewing

Synthetic rotations establish WXYZ input versus XYZW output, distinct camera
and pilot paths, trim-relative timing, quaternion sign/wrap behavior, missing
coverage, gaps and unsupported-category rejection. An integrated synthetic movie
keeps the known pilot direction fixed while the recording camera moves. The
pilot and fixed exports have identical video bytes: guidance does not rotate or
crop the encoded sphere.

The local WebGL player was exercised on the real review: playback, seeking,
free-look orientation holding across a seek, return to the recorded quaternion,
and error-free shader operation. Sampled visual inspection found upright tree
geometry with visible scene-dependent roll/flare; it does not establish an
uninterrupted whole-range perceptual review or exact Studio viewport parity.
Recorded zoom and nonzero tracking categories remain unqualified. Presentation
uses a 90° horizontal FOV; OMAF embedding and flat-video reframing are not implemented.

## Photo precision and metadata

An original-only native 7680×3840 RGB16 TIFF exported with Metal and zero uncovered
pixels. Its checked lens fit used 224/257 inliers with 0.475° p95 angular residual.
Full TIFF decompression matched the renderer's pixel checksum, and GPano XMP
projection/dimensions agreed with the raster. The original was not modified.
A reduced sphere was visually inspected for coverage and vertical; sun flare
and seam/polar detail still require scene-specific review.

The examined INSPs are 8-bit JPEG-based two-lens photos. RGB16 preserves new
interpolation/blend values, with lossless Deflate encoding; it does not add
captured dynamic range. DNG development, unknown color profiles and preservation
of source EXIF/GPS/vendor records in TIFF are not implemented. Existing ICC is
preserved, GPano XMP is written, and the untouched original remains the archive.

## Automated validation

The complete macOS suite passed **368 tests**, including actual Metal execution
and the loopback server's byte-range/allowlist tests. Synthetic tests cover the
new photo pixels/XMP, default pilot path and opt-out, original-only fitting,
corrupt companions, interrupted publication and source preservation. Ruff and
skill validation passed. These checks are separate from perceptual acceptance.

A wheel and source archive build successfully. An isolated wheel installation
outside the checkout completed an original-only **8192×4096, 10-bit HEVC** default
export (three-frame technical smoke test, full decode/tags) and a second native
**7680×3840 RGB16 TIFF** with zero holes. Pillow independently read the TIFF's
three 16-bit samples, Deflate compression and equirectangular XMP. A 300-frame
H.264 guided review was also generated from the installed wheel.

The fresh environment resolved NumPy 2.5.3, OpenCV 5.0.0.93, SciPy 1.18.1,
Pillow 12.3.0 and tifffile 2026.9.9. No checkout import, Studio application,
reference master or manually supplied calibration was used in these exports.
The short 8K check establishes package/format operation, not native-resolution
whole-shot motion acceptance. Version 0.9.0 promotes the same processing code;
its version labels and release documentation replace the development labels.
