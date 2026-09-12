# Image quality in 0.2.0

This pass addresses three specific artifacts: doubled detail at lens seams,
local lens color differences, and row-dependent geometric distortion during
rapid rotation. It does not remove the camera, synthesize missing scene content,
or reproduce a vendor's stabilization pipeline.

## What changed

The overlap estimator unwraps a narrow belt fixed to the lens geometry. It uses
bidirectional DIS optical flow, checks forward/backward agreement, rejects
excessive angular displacement and low-texture/invalid support, and narrows the
detail blend. Longitude wraps; latitude never wraps to an unrelated edge. The
analysis belt provides sampling coordinates only: output detail comes directly
from the original lens images, avoiding a low-resolution seam patch.

Local color balance uses robust sector statistics, rejects clipping/black pixels,
smooths around the belt, bounds correction to at most a factor of two, and tapers
away from the seam. It reduces brighter channel differences instead of spreading
veiling glare into the cleaner lens. Balance adapts over 0.25 seconds and decays
when measurement support disappears. It is not a scene-wide grade or a log LUT.

Rolling-shutter correction uses the embedded sensor readout duration and recorded
angular velocity. Native sensor row determines capture time. Two fixed-point
projection updates account for corrected sampling changing the row itself.
The model assumes constant angular velocity over that frame's readout; it does
not infer high-frequency vibration between recorded attitude samples.

Both corrections are enabled by default. Use `--seam feather --rolling-shutter off`
for a controlled comparison. The old path remains available and is tested.

## Recorded evidence

Evidence comes from the same single A1 unit used in 0.1.0, with independent
original/reference comparisons and fresh original-only render jobs. Private
footage, calibration profiles and metadata dumps are not published.

A rapid-turn exploration estimated about 23.4 ms readout; the original's embedded
value was 21.325 ms. The implementation uses that metadata, not the fitted value.
The table scores the renderer's constant-angular-velocity model using fixed
readout metadata. Each row uses matched scene rays and permits one global
rotation to the vendor reference; the remaining error measures nonrigid geometric
disagreement. Values are 90th-percentile angular errors, not smoothness ratings.

| Frame relative to explored turn | Without row correction | With metadata row correction |
|---|---:|---:|
| −0.2 s, slow motion | 0.216° | 0.219° |
| −0.1 s, held-out turn frame | 0.546° | 0.218° |
| Explored frame | 1.714° | 0.258° |
| +0.1 s, held-out turn frame | 1.160° | 0.316° |
| +0.2 s, held-out turn frame | 0.310° | 0.229° |

Several slower held-out frames changed by only a few thousandths of a degree;
one slightly regressed. Thus the evidence supports the rapid-motion correction,
not a claim that every frame improves or that blur/translation disappears.

An original-only 4K forest sequence (120 frames) reduced mean trusted-overlap
RGB disagreement from 32.60 to 18.39 code values with the new seam path. A second
90-frame rapid-turn sequence with both corrections measured 38.01 to 17.05.
These are internal matched-overlap diagnostics; they exclude unsupported pixels
and are not a whole-image quality score. Still comparisons show less branch and
vehicle-edge doubling. Selected motion frames and review renders supplement the
numerical checks; they are not a claim of exhaustive perceptual review.

The 4K seam pass took about 249 seconds for four seconds of footage including
verification on the development machine, versus about 110 seconds for feather.
The 2K rapid-turn path took about 95 seconds for three seconds of footage, versus
22 seconds for the legacy path. Jobs shared the machine with other analysis;
these are observed costs, not isolated benchmarks or performance guarantees.

## Tests and remaining work

Synthetic tests check subpixel correspondence recovery, lower error on a known
shifted scene, rejection of unreliable/nonfinite flow, periodic boundaries,
bounded color ratios, retention of clean-lens detail, and recovery of a known
fast-rotating rolling-shutter scene. Zero motion/readout preserves the original
projection maps. Existing container, process, cache and complete-encode tests
remain part of CI.

Remaining work includes severe parallax and occlusion, camera/propeller removal,
high-rate inertial fusion, nonconstant motion within a readout, motion blur,
broader unit/firmware coverage, higher bit depth/log/HDR and GPU performance.
Review close objects, the whole intended shot's motion and temporal color changes
before accepting an output as a production master. The release remains alpha.
