# Current qualification

See [the 0.5 report](quality-v0.5.md) for native-resolution/10-bit output, GPU and
gyro qualification. The measurements below describe the original CPU prototype
and are retained as historical evidence; they are not the current defaults.

# Qualification and current limits

A1 Stitcher 0.3.0 is an alpha release. Reusable packaging, automated tests and
safe job handling are separate from perceptual stitching/stabilization quality.

## Real-camera evidence

Development used one A1 unit and two recordings, plus metadata inspection of a
different Insta360 model. This is not a multi-unit or all-firmware certification.
Private footage and camera-specific calibration are not included in this project.

The initial reference fit used seven paired original/vendor frames. Vertical
agreement was 0.139° RMS, with a 0.209° maximum. A later six-frame holdout had five
errors below 0.278° and one rapid-motion outlier at 3.874°. A four-frame holdout
from the other recording was 0.337° RMS, with a 0.658° maximum. These are angular
agreement measurements, not a whole-clip perceptual quality score.

A 12.012-second original-only 2048×1024 proof rendered all 360 frames, had zero
uncovered pixels according to its remap mask, and passed a full decode. A regional
phase-correlation diagnostic over matching fixed views measured 95th-percentile
rotation steps of 1.550° untreated and 0.522° corrected. Physical translation,
parallax and the moving subject remain in that diagnostic; it does not mean
that every kind of shake was removed by 66%.

The packaged CLI was separately exercised on original footage and on a fresh
reference-based calibration run. Every rendered output is checked for frame count,
frame rate, dimensions, SDR color tags, spherical metadata and full decode.
Benchmark results depend on output/lens resolution, decoder cost and competing
workloads. The CPU prototype is slower than real time; no GPU speedup is claimed.

## Automated tests

The suite generates synthetic lens tracks, an indexed INSV trailer, and a known
moving-camera attitude track. A complete conversion checks that recorded-attitude
correction holds a synthetic scene more steadily than the baseline. Additional
checks cover:

- Legacy/indexed v3 reading, corrupt bounds, duplicate/overlapping records and
  malformed protobuf values.
- Lens projection/inversion, relative rotation recovery, proper-rotation
  validation, and float32 strip rendering against the full-frame reference.
- Mount/time recovery against unseen synthetic observations and poor reference
  rejection.
- Output frame/color/spatial metadata, full decode, fast-start offset relocation,
  and 32-bit offset promotion.
- Process deadlines, early EOF, stalled encoders, cleanup, output locks, no-clobber
  writes, receipt rollback, checksum-based reuse and batch path handling.

CI runs on macOS and Linux, with Python 3.12 and Linux Python 3.13. The CI result
for an exact commit is the authority for that commit; a workflow definition alone
is not evidence that those runners passed. The installed wheel is checked outside
the checkout so an editable source import cannot hide packaging mistakes.

## Before production-master acceptance

Inspect the intended interval in motion, including seams through nearby subjects,
horizon changes, body/propeller visibility and subject shape. Keep the original,
source-frame mapping, calibration and receipt. Review especially fast maneuvers;
native-row correction uses embedded readout duration with average-rate motion
by default, or optional row trajectories. Anchored raw gyro, refitted exposure
midpoints and camera-bound visibility masks are available as experimental
options. None establishes high-frequency image timing or full aircraft-removal
parity. Visibility masks can select actual alternate-lens pixels but cannot
reconstruct doubly occluded detail. Adaptive seams remain a separate option.
See the [0.7 evidence](quality-v0.7.md) and the linked earlier measurements.

The original prototype output path was 8-bit SDR BT.709. Current 16-bit processing and 10-bit output
reduce new rounding; they do not establish log/HDR support. I-Log/D-Log, HDR, audio preservation, other camera models, and broad hardware/firmware
coverage are not qualified. The application rejects unrecognized profiles rather
than applying an assumed transform. Source color tags alone do not establish a
new model's color science.

The output mask can prove coverage but cannot prove invisible seams. A complete
decode cannot prove compelling editing. Preserve those distinctions in bug reports,
agent skills and downstream media libraries.
