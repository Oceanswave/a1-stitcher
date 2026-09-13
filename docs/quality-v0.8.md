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

Two complete 20.02-second intervals compare matched gyro/exposure/trajectory
controls with the image refit. Both members of each pair use the final tapered
multiband model, 1920-pixel lens decodes and 2K/H.264 review spheres.

| Interval | Gyro control | Image refit | Reduction | Studio reference | Tracked candidate pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ridge, fitting interval | 0.22868 | 0.14711 | 35.7% | 0.02352 | 599/599 |
| Forest, separate recording | 0.20984 | 0.15861 | 24.4% | 0.13033 | 541/599 |

Motion values are p95 angular acceleration in degrees per frame squared, measured
from rigid image tracks; they are not absolute horizon error. The forest reference
measured 541/599 pairs. Missing pairs were not bridged. Local residual p95 on
forest changed from 0.65941° to 0.66033°, so motion and local geometry
need separate assessment. Studio remains smoother on both intervals. A prior
recorded-attitude ridge screening measured 1.03823 versus 0.02352 for Studio;
the combined gyro/image path is substantially steadier, but that larger change
cannot be attributed to the image timing fit alone.

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

Local validation passed 342 tests, including 66 cases requiring actual Metal
execution, with 88% coverage. Rockybot CI ran Python 3.12 and
3.13: 276 passed and 66 GPU-specific cases skipped in each Linux job. Ruff and
skill validation passed. Package build and an outside-checkout wheel test
produced and fully decoded a native 8192×4096, 10-bit HEVC export using image
timing, trajectory rows, reviewed visibility, multiband and GPX together.
The three-frame installed-package test is a technical integration proof, not
whole-motion qualification. GPX contained 398 points covering its entire source.

Two native-lens comparisons covered 600 consecutive frames each: full
3840-pixel lens decodes, 4096×2048 ProRes 422 HQ output, recorded attitude, and
otherwise matching settings. The final multiband renders and unchanged flow
controls passed full decode with no uncovered pixels. These are 20.02-second
sequences, not isolated stills.

| Native-lens interval | Flow brightness variation | Final multiband brightness variation | Studio brightness variation | Flow / multiband local residual p95 (°) |
| --- | ---: | ---: | ---: | ---: |
| Chase | 0.0019391 | 0.0019268 | 0.0009476 | 0.64661 / 0.64396 |
| Forest | 0.0034216 | 0.0034313 | 0.0027949 | 0.66177 / 0.65801 |

Brightness variation is the p95 absolute second difference of six view means,
normalized to 0–1. It includes scene/exposure changes and is not a seam-specific
quality score. Small changes in this diagnostic do not justify promoting
multiband over flow globally. Native detail, moving seams and flare still require
visual review; the final support taper has stronger controlled synthetic evidence
than evidence of a broad real-footage advantage.

Four additional 600-frame, 2K/H.264 intervals were screened during development:
ridge action, evening mountains, ridge follow and ridge opening. All decoded,
and each benchmark attempted all 599 motion pairs. Their recorded-attitude motion
p95 values were 1.03823, 0.44037, 0.99855 and 1.19913, respectively; the corresponding
Studio values were 0.02352, 0.00969, 0.10842 and 0.01924. These screening renders
precede the final support taper and establish remaining motion differences,
not final-model seam qualification. Across the native and screening sets, six
unique source intervals were checked. They all come from one camera unit.

Development receipts retain their actual version label, settings and source-tree
fingerprint; they were not relabeled after rendering. The final timing/native
repeats and installed-package proof use 0.8.0. Automated all-frame coverage and
sampled browser/native-overlay inspection remain separate: uninterrupted human
acceptance of every sphere direction is not claimed. All new algorithms remain
opt-in, while established finishing quality and automatic Metal stay the defaults.

No personal footage, original filenames, per-unit profiles, vendor binaries,
models or disassembly are distributed. See [format notes](format.md),
[Studio parity](studio-parity.md), [NOTICE](../NOTICE), and the README's
[source/archive importance table](../README.md#what-conversion-preserves-and-bakes-in).
