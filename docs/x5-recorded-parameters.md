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
with an A1 five-coefficient profile or third-party per-unit constants. The vendor
projection equation, distortion ordering, angle/translation convention, and crop
mapping remain unqualified; no lens matrix is silently supplied to rendering.

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

No clean Studio reference was generated during this inspection: GUI automation
did not return before cancellation, and a supported headless export interface was
not established. No automation permission, SDK, vendor runtime dependency or
security setting was installed or changed. The next reference-generation step
requires working access to the existing Studio controls, not lens recalibration.

X5 sphere export stays blocked. A1 behavior, model/profile boundaries and the
existing `a1-stitch` identity remain unchanged.
