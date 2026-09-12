# 0.6 motion and Studio investigation

This pass adds an independent varying-motion sensor-row model, repeatable
source-frame heading, exposure inspection and faster gyro queries. It does not
establish parity with Studio. The ordinary defaults retain recorded attitude,
average-rate rolling-shutter correction, 8K/native processing, 10-bit HEVC, flow
seams and automatic Metal selection. Fixed heading from original frame zero is
new; `--heading-reference-frame -1` restores clip-start heading.

## Varying motion through the sensor scan

`--rolling-shutter-model trajectory` samples 33 orientations across the embedded
readout interval. Each lens gets the inverse center-to-capture quaternion in its
own coordinate system. Two native-row updates determine each pixel's capture
orientation. Continuous quaternion signs and normalized linear interpolation
avoid long-path interpolation. CPU projection, overlap analysis and Metal use
the same model. A synthetic textured scene with 55/70 Hz changing rotation and
a 22 ms readout had less than one fifth the reconstruction error of the
average-rate approximation. Constant-rate cases match the analytic rotation.

The selected trajectory still matters: recorded attitude does not become a
high-rate sensor measurement just because more row samples are requested. The
optional per-unit gyro profile supplies anchored integration, with the existing
100 ms default anchor interval. Neither path removes captured motion blur.

## Matched real-footage results

Three complete 90-frame, 8192×4096 ProRes sequences were rendered from native
3840-pixel lenses: one rapid forest turn with recorded attitude, the same turn
with calibrated gyro, and a second recording with that gyro profile. All passed
full decode, color/projection metadata, frame count and checksum checks.

The diagnostic is the same as in [0.5](quality-v0.5.md): a fixed 90° reframe,
one frame-zero alignment, background feature tracking and frame-to-frame affine
acceleration at 960×540. It includes translation, parallax and tracking noise;
it is not a perceptual smoothness score. The transfer interval has a prior CLI
baseline but no source-matched Studio export.

| Sequence / orientation | Previous average-rate model: median / p95, px | New trajectory: median / p95, px |
| --- | ---: | ---: |
| Forest turn, recorded attitude | 1.580 / 14.185 | 1.621 / 12.748 |
| Forest turn, calibrated gyro | 0.552 / 3.059 | 0.494 / 3.348 |
| Second recording, calibrated gyro | 0.472 / 2.015 | 0.553 / 2.232 |
| Forest turn, Studio reference | 0.407 / 2.048 | — |

These results are mixed. The recorded-attitude tail improves about 10%, while
the median worsens about 3%. The gyro forest median improves about 10%, but its
tail worsens about 9%; the transfer median/tail worsen about 17%/11%. Consequently
**`velocity` remains the default** and `trajectory` is explicitly experimental.
The more detailed mathematical model has not yet established better real-footage
motion. Source-matched sampled stills also retain visible blur in both Studio and
CLI outputs. These checks do not constitute uninterrupted perceptual review.

## Gyro query performance

Repeated queries previously passed strided sensor columns to interpolation,
causing copies of the entire flight during each integration step. The new code
stores contiguous components and reuses the correction at each recorded anchor.
The integration model, time bounds and frame clock stay the same. Query batching,
order and repeated calls are tested to preserve orientation results.

On the local M1 Max, 20 queries of 33 row orientations against an approximately
879-second recording took **12.55 seconds before / 0.085 seconds after: 147×**.
The maximum orientation difference was 5.7×10⁻¹⁷ radians. This measurement begins
with a cold anchor cache and excludes loading, rendering, decode, seam analysis
and encoding. It is **not** a 147× export-speed claim. The earlier Metal benchmark
in the 0.5 report likewise measures a separate, bounded stage.

A complete 90-frame native 8K ProRes export using the new experimental trajectory
path took **155.75 seconds before / 80.81 seconds after** the optimization, about
**1.93× faster**. The two output files have identical SHA-256 checksums. This is
one before/after run, including verification, not a repeated throughput benchmark
or a comparison against the older average-rate renderer. It shows that the more
frequent gyro queries no longer dominate this particular export.

## Exposure and remaining work

Inspection decodes the observed 16-byte exposure layout and reports durations,
cadence, gaps and potential half-exposure variation. The two source recordings
had shutter ranges of approximately 0.178–3.664 ms and 0.292–3.583 ms. A
variable exposure-to-gyro adjustment could therefore matter, but the existing
profile already fits a constant video/attitude offset. No extra adjustment is
applied until shutter-edge semantics and image timing are calibrated together.

See [the Studio functionality matrix](studio-parity.md) for the remaining
spline/direction-lock, multiscale fusion, camera/propeller removal, occlusion,
tracking and unsupported ingest work. Proprietary code and models are not
packaged. The CLI features are independently authored.

## Regression and packaging checks

The final local suite passed **255 tests**, including 24 actual Metal parity
cases; Python coverage was **90.12%**. Unsupported GPU hosts explicitly skip
those 24 cases. Tests cover known changing-motion scene reconstruction,
constant-motion equivalence in both lenses, separate-export heading continuity,
query partition/order invariance, malformed exposure records, bounded preflight,
FFmpeg integration, no-overwrite receipts and checksum-verified resume.

An installed wheel was exercised outside the checkout on the full 90-frame
native 8K ProRes gyro/trajectory export, including full decode verification.
The native Swift/Metal sources are packaged; no vendor runtime is required.
The skill and options reference describe the measured default/experimental split.
