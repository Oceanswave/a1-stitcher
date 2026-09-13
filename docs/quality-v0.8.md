# 0.8 image timing, mask proposals and continuous comparisons

Version 0.8 adds four independent capabilities: contiguous Studio benchmarks,
image/gyro timing plus row-readout fitting, reviewed native obstruction proposals,
and optional three-band overlap blending. This remains an alpha release.
The established finishing defaults are retained; explicit experiments are not
promoted merely because they are newer.

## Timing evidence

Three 600-frame real intervals were analyzed from the same camera. Native
feature analysis used 768-pixel lenses and four contiguous temporal blocks.
The nominal-clock forest and chase fits were rejected for failing the 1% held-out
median improvement gate. Rejected fits wrote evidence and no calibration.

The exposure-clock ridge fit used 90,222 tracks, including 42,589 held-out tracks.
It fitted a −1.708 ms adjustment and 0.9730× readout scale. Held-out median angular
error changed from 0.07878° to 0.07777° (1.3% improvement); p95 changed from 0.52205°
to 0.52419° (0.4% worse, within the explicit 1% tail tolerance). This is a small
local gain, not proof of universally better stabilization. The schema-3 result
is bound to the frame-rate/readout mode, gyro profile and 0.1-second anchor spacing used during fitting.
Three same-frame-rate recordings reported native readouts of 21.267–21.325 ms.
The compatibility check therefore allows 1% readout variation; it rejects larger
scan changes and different frame rates. Each source retains its own measured
readout before the fitted multiplier is applied.

A complete 20.02-second ridge render with gyro interpolation, the image refit and
trajectory row correction had a p95 angular-acceleration diagnostic of 0.14698°
per frame squared, versus 1.03823 for recorded attitude. The corresponding Studio
reference measured 0.02352. That is about an 86% reduction relative to the older
processing path, with substantial remaining separation from Studio. It must not
be attributed to the 1.7 ms change alone: gyro interpolation, exposure clock and
row model changed too. A matching gyro-only control isolates the new fit: 0.22939 → 0.14698, about
35.9% lower. On a separate forest recording with the same capture mode, the
matching gyro control measured 0.22397 versus 0.16215 with the ridge-derived
profile (27.6% lower). Studio measured 0.13033 there. Forest motion tracking
succeeded on 540/599 candidate pairs and 541/599 reference pairs; missing pairs
were not bridged. Local residual p95 was slightly worse with the forest image
fit (0.66013° → 0.66612°), reinforcing that motion and local geometry must be
judged separately. These comparisons used 1920-pixel lens decodes and 2K/H.264
review spheres, with identical settings within each timing pair.

## Obstruction proposals

A 24-sample, 20.02-second chase interval produced native overlay sheets. The first
prototype incorrectly included black image-rim regions. Eroding temporal image
support removed that failure, covered by a synthetic regression test. Refined
proposals still contained side-rim fragments, which were rejected during review.
Six top-housing fragments in one lens were retained for a render experiment; the
other lens had no retained exclusion. The complete 600-frame 2K/H.264 test passed
full decode without uncovered pixels. The inspected evidence comprised six
sampled overlays per lens, not every native frame.

This does not establish complete propeller segmentation. Pale housings, intermittent
blades, shadows and nearby static objects can defeat the heuristic. Profiles are
camera/accessory-bound, require review, and check alternate clipping/contrast only
when a mask forces replacement. Their JSON and private preview sheets retain
source mapping. Doubly occluded or unusable replacements fail rather than inventing
hidden detail. Zero holes is a technical gate, not visual acceptance.

## Seam model and comparison method

The new mode keeps a narrow native-detail transition and adds two lower-frequency
difference bands over wider angular transitions. It operates in the calibrated
±8° overlap belt, uses correspondence/visibility/clipping support gates, and caps
per-frame log-gain changes. It does not average pixels over time. CPU and Metal
share the analysis and differ only in final projection/sampling arithmetic.
An added regression exposed a hard correction boundary when the measured overlap
was narrow. The final model fades inside valid support. In isolated 16-bit constant
signal tests, the maximum adjacent-pixel brightness step falls from 1,308 code
values to 527 with narrow overlap and 342 with wider overlap; distant pixels stay
identical. This measures synthetic blending behavior, not real-footage improvement.
This is an independent bounded-belt implementation, not Studio's image-fusion code
or OpenCV's full-panorama MultiBandBlender.

`benchmark` decodes every frame in the selected contiguous range, builds six
fixed 90° views per input and fits one global alignment at the beginning. It
reports all attempted motion pairs, failed tracking, angular acceleration, local
inlier residuals, brightness second differences and per-face detail. No per-frame
alignment conceals candidate motion. Reduced-resolution metrics are affected by
real scene movement, parallax and changing exposure; they do not certify native
seams, absolute horizon or whole-shot perception. Browser playback with sampled
observations is recorded separately from all-frame automated coverage.

## Final qualification results

Local validation includes 342 tests, including 66 cases requiring actual Metal
execution, with 88% coverage. The first Rockybot CI pass ran Python 3.12 and
3.13: 274 passed and 66 GPU-specific cases skipped in each Linux job. Ruff and
skill validation passed. Package build and an outside-checkout wheel test
produced and fully decoded a native 8192×4096, 10-bit HEVC export using image
timing, trajectory rows, reviewed visibility, multiband and GPX together.
The three-frame installed-package test is a technical integration proof, not
whole-motion qualification. GPX contained 398 points covering its entire source.

Longer comparison qualification is recorded in the table below after the
remaining native controls finish. Development comparison receipts can retain
the preceding version label; they record the actual processing settings and
source-tree fingerprint. The installed-package proof uses version 0.8.0.

No personal footage, original filenames, per-unit profiles, vendor binaries,
models or disassembly are distributed. See [format notes](format.md),
[Studio parity](studio-parity.md), [NOTICE](../NOTICE), and the README's
[source/archive importance table](../README.md#what-conversion-preserves-and-bakes-in).
