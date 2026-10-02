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

The corresponding forward diagnostic is:

```sh
a1-stitch recorded-calibration SOURCE.insv --lens 0 --ray X Y Z \
  --redact-path --output NEW_PIXEL.json
```

The ray uses the same lens coordinate system and can have any finite nonzero
length. Normalization avoids numerical overflow/underflow. The command rejects
far-branch, folded and uncovered rays, then checks the projected pixel's inverse
against the supplied direction. `--ray` and `--pixel` are mutually exclusive;
both require `--lens`. No extrinsic or gyro transform is applied.

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

After the user enabled client access and restarted ChatGPT, Accessibility trust,
screen-capture preflight and harmless Studio control queries succeeded. Four new
native reference exports were completed through Studio 6.0.6 using checksummed
working copies and independent saved projects. The task did not change permission
or security settings, accept agreements, adopt an SDK or add a vendor dependency.
Existing originals, projects and reference exports were preserved.

Each recording has an unstabilized optical export and a corresponding FlowState
export, both with direction lock off, accessory 0 (guards off), optional stitching
optimization and chromatic calibration off, HDR/APMP off, source frame rate and
retained stereo 48 kHz AAC. Export dialogs and actual saved project settings were
retained privately. The short recording's saved Color Plus and motion-blur flags
are off, but both long-recording snapshots retain those flags as true. The long
pair therefore cannot be certified as unenhanced; the `clean` output names are
preparation labels, not an acceptance claim. That pair was preserved and replaced
by new full-range optics/FlowState exports with Color Plus and Motion ND verified
off in both the GUI and saved project snapshots. An intervening two-frame optics
export was also preserved as a rejected artifact, with the replacement's zero
left/right trims verified before export. Both replacements fully decoded with
audio and contain 3497 frames covering source 0 through 3495 plus the excluded tail.

A saved multiframe-denoise flag remains true without an active video enhancement
switch. Read-only inspection of the installed Studio 6.0.6 binary traced the
`pro::InstaHelper::CreateMultiFrameDenoiseFilter` path: it checks metadata cache and
video eligibility, then returns a null filter for a panoramic asset. The global
`filter/denoise` setting and a separate `studio::PostFilterFactory` construction
path also exist. This establishes a mode-dependent gate, not observation of the
live export filter graph. Binary runtime logs were unreadable and no live filter
receipt was available; absence of all temporal vendor processing remains unproven.

All four exports fully decode as 7680x3840 HEVC at 30000/1001 fps. The short pair
contains 167 frames from source frame zero. The long pair contains 3497 output
frames, while the original has 3496. Its inherited left trim was cleared before
export. The final additional output frame has no new source frame and must be
excluded from a source-mapped comparison; its small differences from the preceding
frame do not establish additional captured motion. Use only the covered original
range 0 through 3495. Container counts alone do not certify every intermediate
frame's correspondence.

Private comparisons used native 3840-square images from both lenses and six
perspective faces sampled from native references at three frames per recording.
The centered endpoint model produced holdout median angular residuals of about
0.045–0.209 degrees, versus 0.190–0.524 for an uncropped endpoint model. Endpoint
and dimension scaling differed too little to qualify their distinction by these
image measurements alone; the endpoint convention remains based on function
inspection. Fitted rotations and spatial residuals are diagnostic evidence, not
qualified lens extrinsics or seam profiles. Recorded angle slots do not directly
establish the opposing lens poses without the renderer's basis/index conventions.
An experimental search adding a fixed lens-index half-turn reduced relative-pose
disagreement to about 0.305 degrees on the short recording and 0.287 degrees on
the corrected long recording. The convention was selected by a search and is
neither independently verified nor applied to the renderer.

Raw-to-FlowState image fits at 20 sampled frames across both recordings produced
median angular residuals of about 0.019–0.067 degrees after one rigid rotation per
frame using the corrected long references. These measure sampled content
correspondence and applied pose under the recorded settings;
they do not qualify an independent stabilizer or horizon quality. A gyro mounting,
bias and clock experiment fitted six short-clip gravity poses, held out five more,
then transferred to the longer recording. Holdout RMS was about 0.013 degrees but
transfer RMS was 10.65 degrees, reaching 17.47 degrees near the end. This failure
persists after disabling the long recording's Color Plus and Motion ND. Gravity-only
fits leave heading, accelerometer fusion, gyro bias and image/readout timing
confounded. No fitted mounting, bias or clock constant was adopted.

Decoded audio is identical within each raw/FlowState pair. Across two short-clip
and five long-clip windows, reference audio lags the decoded source by 1103–1104
samples (about 23 ms), with correlation about 0.943–0.994. The references also
contain more decoded audio samples than the originals. This repeatable vendor
decode/export observation does not establish acoustic/visual sync or authorize
padding/offsets in independent output. Visible/audible event validation remains
required; source PCM companions still preserve their original timestamp mapping.

Further qualification uses native 7680x3840 standard SDR spheres with explicit source
frame ranges and retained audio. Record the actual lens-guard/accessory override,
FlowState and direction-lock settings and disable ClarityPlus, denoising and other
enhancements. Use separate output names and preserve saved projects and existing
exports. An unstabilized export isolates optical/seam geometry; a corresponding
FlowState export exposes gyro/horizon behavior. Include moving intervals from
both originals, rapid rotations, near seam objects and observable audio events.

X5 sphere export stays blocked. A1 behavior, model/profile boundaries and the
existing `a1-stitch` identity remain unchanged.
