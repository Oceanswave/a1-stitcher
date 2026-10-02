# Recovering recorded X5 calibration parameters

X5 originals already contain camera-specific optical parameters. Manual lens
recalibration is not the first step. Development builds recover the recorded
parameters with:

```sh
a1-stitch recorded-calibration SOURCE.insv --frame 3000 \
  --redact-path --output NEW_PARAMETERS.json
```

The command checks the standard SDR X5 input contract, reads bounded trailer
metadata, validates the observed parameter layouts and inventories the recorded
exposure clock. It creates a new JSON file only, checks source identity before
and after inspection, and reports the source identity and a reusable parameter
fingerprint. The fingerprint binds camera/firmware, capture mode, lens records,
accessory entries, crop/readout, and recorded gyro parameters. Exposure/frame-zero
timestamps remain specific to each recording. Keep exported per-camera parameter
files private; they are not repository fixtures or rendering calibrations.

## What is established

Read-only inspection of the installed Studio 6.0.5 protobuf schema identifies:

| Metadata field | Schema meaning | Current interpretation |
| --- | --- | --- |
| 104 | `guard_detected_type` | 0 unknown, 1 A, 2 S, 3 OFF, 4 A_S; other values remain unsupported labels |
| 111 / 112 | `offset_v6` / `original_offset_v6` | Observed finite 56-value record: two 27-value lens blocks and a trailing flag |
| 136 | `capture_offset_version` | 4 identifies `OFFSET_V6`; required by this command |
| 64 | `pts_type` | 2 identifies `VIDEO_PTS_EXPOSURE_FILE`; the raw value is preserved |
| 31 / 37 | `gyro_calib` / `orientation_calib` | Opaque payloads; fingerprints retain their identity without assigning undocumented units or transforms |

Each observed V6 lens block holds xi, four intrinsic values, three extrinsic-angle
values, three translation values, thirteen distortion slots, two sensor dimensions
and a lens-type value. The command currently accepts the observed type 113 and
square sensor layout. It preserves all thirteen slots rather than replacing them
with an A1 five-coefficient profile or third-party per-unit constants. The
independent polynomial and observed crop mapping are now available for explicit
ray diagnostics below. Angle/translation conventions and production image
quality remain unqualified; no lens matrix is supplied to sphere rendering.

Field 145 contains observed named entry lists: six doubles per name in group 1,
one double per name in group 2, and one integer per name in group 3. Names include
`bare`, `ProtectorA`, `ProtectorS`, `ProtectorAS`, and dive/thermal variants. Their
slots are retained with their original grouping. Their equation and units are
not established. An explicit OFF detection can identify the `bare` candidate,
but no candidate is applied. A/S names are not asserted to mean Standard/Premium.

The exposure inventory checks the observed uint64-microsecond/float64-second
record-4 layout, increasing timestamps, positive bounded shutter durations, a
unique exact first-video timestamp, complete video-frame coverage, and cadence.
`--frame` reports the ordinal record's timestamp and shutter duration plus an
unapplied midpoint candidate. Residuals against the playback clock are measured,
not corrected. This establishes an observed ordinal correspondence; it does not
prove the exposure edge or sensor-to-image timing.

## Private observations and unresolved interpretation

Two inspected originals from one X5 unit have identical V6 lens records, captured
offset version 4, thirteen distortion slots per lens, and matching current/original
V6 strings. They contain named accessory candidates, guard detection OFF, a
recorded 1.6 ms gyro timestamp parameter, 21.244 ms readout, and crop dimensions
5376 to 5312. Record-4 frame zero appears at ordinal 5. The longer recording's
exposure timestamps differ from 30000/1001 playback timing by up to about 4.7 ms;
nominal 30 fps accumulates much larger error. The command reports these values
without applying a gyro shift or exposure midpoint convention.

Both sources lack an `orientation_calib` metadata payload. An upstream
[telemetry-parser model convention](https://github.com/AdrianEddy/telemetry-parser/blob/master/src/insta360/mod.rs)
assigns X5 `yzX`, but that convention's coordinate system does not by itself
establish this renderer's gyro-to-lens matrix. The six `gyro_calib` values are
also not assumed to be that matrix or a proven bias correction.

One saved Studio project selects camera accessory 0 and another selects 23,
despite both originals reporting guards OFF. This is a cached project observation,
not a verified export recipe. Capture detection and subsequent editor overrides
must stay distinct. The official
[X5 FAQ](https://intercom.help/insta360support/en/articles/11123202-faqs-for-x5)
says the camera detects guards and Studio selects appropriate parameters; it does
not define field 145 or certify this independent interpretation.

## Applying recorded parameters to a diagnostic ray

```sh
a1-stitch recorded-calibration SOURCE.insv --lens 0 --pixel U V \
  --redact-path --output NEW_RAY.json
```

`U V` are pixel-center coordinates in a decoded native lens track. The explicit
diagnostic applies recorded intrinsics and all thirteen distortion slots and
returns a unit ray in that lens's x-right, y-down, z-out coordinate system.
It requires guards OFF, unchanged current/original parameters and the observed
centered square crop. Invalid pixels, nonconvergence, projection singularities
and unsupported variants fail. It does not supply a sphere-rendering profile,
apply accessory entries or interpret an IMU/extrinsic transform.

Read-only inspection of Studio 6.0.5's `OmniProjection<RadtanDistortPro>` type,
offset parser, forward projection and backprojection establishes the polynomial
below. A1's shorter model has a separate geometry type. The code independently
implements the mathematics and a damped Newton inverse; it neither imports the
application nor includes vendor implementation code, binaries or unit constants.

For normalized coordinates `x,y`, let `r=x*x+y*y`. In recorded slot order `c0..c12`:

```text
R = 1 + c0*r + c1*r^2 + c2*r^3 + c3*r^4 + c4*r^5
A = c5 + c7*r
B = c6 + c8*r
xd = x*R + A*(r+2*x*x) + 2*B*x*y + c9*r + c11*r^2
yd = y*R + B*(r+2*y*y) + 2*A*x*y + c10*r + c12*r^2
```

The last eight slots are four radius-dependent tangential terms and four prism
terms, not OpenCV tilt coefficients or an extra radial pair. The unified-xi
projection follows the same sphere mapping used in the A1 implementation; the
[OpenCV omnidirectional documentation](https://docs.opencv.org/4.x/d3/ddc/group__ccalib.html)
describes that underlying model, not the vendor's thirteen-slot extension.

Inspection of `OffsetConvert::convertOffset` and geometry resize identifies a
centered crop followed by endpoint scaling `(decoded_size-1)/(crop_size-1)`.
The diagnostic requires source crop dimensions matching the recorded square
sensor and an even centered crop. It subtracts the right lens's concatenated
sensor offset before cropping. No assumption is made about other window layouts.
The vendor functions identify a convention; clean image comparisons still need
to establish which stages Studio applies for these captures and accessories.

Synthetic tests isolate every distortion slot with hand-computed expectations,
check the analytical Jacobian against finite differences, invert asymmetric
distorted coordinates, recover known sphere rays and check crop/principal-point
mapping. They reject edited/guarded/unsupported layouts and folded or uncovered
rays. These mathematical checks do not establish stitching or FlowState quality.

Private original-image checks measured eleven three-frame motion pairs from one
recording and seven from the other, using native 3840-square left-lens images.
Robust rigid fits had median inlier angular residuals of roughly 0.065–0.185
degrees and 95th-percentile residuals of 0.195–0.301 degrees. These are sparse
single-lens measurements with translation, parallax and readout confounders,
not full-interval seam measurements or native sphere acceptance.

A provisional raw-gyro axis/time fit used six pairs for training, five independent
pairs from the first recording for holdout, and seven from the second for transfer.
Candidate playback/exposure/midpoint clocks produced about 4.4–6.0 degrees/second
holdout RMS and 6.9–7.7 degrees/second transfer RMS. These residuals do not justify
applying a mounting matrix, bias or timing shift. The experiment cannot distinguish
the image exposure edge from a fitted shift. No fitted per-unit constants or
automatic timing correction enter the CLI, defaults or repository fixtures.

## Next validation

Use the recovered originals' parameters first. Establish the V6 projection/crop
convention with independent source-ray/reference correspondences, then establish
gyro axes and timestamp sign against motion measured from the original images.
Validate transfer across the already available recordings before deciding whether
additional capture is needed. Clean source-mapped native Studio comparisons must
record accessory overrides, stabilization/direction-lock and enhancement settings.
Check full moving intervals for seams, horizon, rapid rotation and nearby geometry,
and verify audio against visible/audible events. Existing ClarityPlus references
and parameter parsing alone cannot establish those results.

No clean Studio reference was generated. On the latest permission recheck,
`AXIsProcessTrusted()` still returns false for the execution client and the
read-only Studio window-name query fails with `osascript is not allowed assistive
access` (-1728). Screen-capture preflight succeeds. A supported headless export
interface has not been established. No automation permission, SDK, vendor runtime
dependency or security setting was installed or changed. Reference generation
requires Accessibility access for the client running osascript, or clean exports
from the already available originals, rather than lens recalibration.

Required references are native 7680x3840 standard SDR spheres with explicit source
frame ranges and retained audio. Record the actual lens-guard/accessory override,
FlowState and direction-lock settings and disable ClarityPlus, denoising and other
enhancements. Use separate output names and preserve saved projects and existing
exports. An unstabilized export isolates optical/seam geometry; a corresponding
FlowState export exposes gyro/horizon behavior. Include moving intervals from
both originals, rapid rotations, near seam objects and observable audio events.

X5 sphere export stays blocked. A1 behavior, model/profile boundaries and the
existing `a1-stitch` identity remain unchanged.
