# Studio comparisons and color correction in 0.3.0

Matched Studio frames exposed a color-balancing regression: starting a clip
during a turn could paint a dark, colored arc into clear sky. The original lens
pixels and the Studio reference had no such arc. This was an error in our color
extrapolation, not evidence of a propeller in the source.

## What changed

Color correction now tapers to zero at the edge of the measured ±8° overlap
belt, instead of extending to ±24°. Unsupported sectors no longer receive a
correction interpolated between distant measured regions. A single missing
sector can bridge; larger gaps taper toward neutral correction. The temporal
balance and bounded, darker-channel preference remain. Synthetic tests check
that clean pixels outside the belt and large unsupported arcs stay unchanged.

Optional `--seam adaptive` searches for a closed, low-cost path around the sphere
within ±4° of the optical seam. Cost reflects photometric disagreement,
correspondence confidence and distance from the optical seam. A dynamic program
closes the longitude boundary; spatial smoothing and a 6°/second movement limit
reduce path crawling. Final pixels still sample the original lenses. This mode
can avoid difficult overlaps but does not identify which object is the camera,
recover hidden detail, or guarantee improved perceptual quality. `flow` remains
the default.

Projection and cubic sampling skip lens pixels with zero output weight. The
legacy feather path was pixel-identical to 0.2.0 in both real-frame benchmarks;
tests also compare compact sampling and native-row maps against dense sampling.
Both lens tracks are now decoded through one demuxer and a paired frame stream,
avoiding competing reads of the same external-drive file. Preflight requires
matching track start times as well as dimensions, frame rates and counts. An
integration test compares the first and last decoded lens pairs with independent
source-frame decodes, including lens order and the nonzero starting frame.

## Reference evidence

Seven matching moments from a three-second turn were compared with a known
full-sphere Studio export. Separate sampled forest and vehicle frames provided
additional context. Each comparison allows a single global rotation, with no
local geometric warp or exposure/color fit. The new `a1-stitch compare` command
preserves both original and aligned images, mapping, input identities, rotations
and matched-inlier error. Per-frame alignment hides global attitude differences;
the unaligned views, alignment changes and full motion require separate review.

The conspicuous sky arc disappeared in the explored clip-start still. In the
90-frame conversion, temporal color adaptation had already reduced the original
artifact, so improvement was smaller. A fixed reference-sky region showed these
mean absolute RGB differences (8-bit code values):

| Sample frame | 0.2.0 | Corrected fixed seam | Experimental adaptive seam |
|---|---:|---:|---:|
| 0 | 2.279 | 2.262 | 2.271 |
| 15 | 2.080 | 2.057 | 2.072 |
| 29 | 3.456 | 2.551 | 2.557 |
| 32 | 3.284 | 3.023 | 3.057 |
| 45 | 2.114 | 2.064 | 2.086 |
| 60 | 2.375 | 2.168 | 2.153 |
| 89 | 2.594 | 2.432 | 2.391 |

This exploratory metric uses the same rectangle and reference-derived blue-sky
mask in all three versions. It measures one region, not whole-image quality.
Matched-inlier geometric error stayed broadly similar and sometimes increased
slightly as color changes affected feature matches. This is a color regression
fix, not a claim of additional geometric or stabilization improvement.

On the same 90 frames, the adaptive path reduced mean internal selection cost
from 0.842 to 0.770; its maximum per-frame movement was 0.2002°, consistent with
6°/second at the source's fractional frame rate. That objective is not a quality
score. The visible differences were modest, so the experimental mode remains
opt-in. Strong lens flare and fast-turn motion blur also remain in Studio's
reference; this pass does not claim to remove them.

## Performance evidence

Observed core-render medians on an Apple M1 Max, four OpenCV threads, with one
warm-up and three measured iterations per case, using cached original lens
frames and 21.325 ms row correction:

| Output / lens width | Seam | 0.2.0 seconds/frame | 0.3.0 seconds/frame |
|---|---|---:|---:|
| 2048 / 1440 | feather | 0.661 | 0.511 |
| 2048 / 1440 | flow | 1.102 | 0.940 |
| 4096 / 3840 | feather | 2.334 | 1.959 |
| 4096 / 3840 | flow | 4.207 | 3.515 |

These exclude file reads, decoding, encoding and verification. The observed
fixed-flow core improvement was about 15–16%; it is not a GPU or real-time claim.
Full-job timing was affected by intermittent external-drive reads: one dual-reader
run took 322 seconds, while the subsequent single-reader adaptive run completed
in 90 seconds. Those jobs differ in seam mode and I/O conditions, so their ratio
is not a controlled end-to-end speedup measurement.

## Remaining work

Read-only Studio inspection exposed seam-finder, propeller-guard and gyro-filter
feature names. These suggested experiments, not exact algorithms. No vendor
code, masks, shader programs, models or libraries are included or invoked.

The roughly 1 kHz raw gyro stream was decoded and compared with recorded attitude.
Fitted axis/timing relationships still left several degrees/second of residual
disagreement and transferred imperfectly between recordings. It is not enabled
as a stabilization source. High-rate inertial fusion, camera/propeller masking,
severe parallax/occlusion, motion deblurring, GPU rendering, log/HDR and broader
camera/firmware coverage remain open. The package remains alpha.
