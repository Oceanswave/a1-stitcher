# Observed A1 format

These notes describe indexed recordings examined during development. They are
not a vendor specification or a compatibility claim for every camera/firmware.

## Container and trailer

An A1 INSV is an ISO BMFF/MP4-family file containing two HEVC square fisheye tracks
and additional camera metadata. The inspected recordings also contain a per-frame
`INS.Subtitle`/`mov_text` track. That track is not needed by this implementation.

The final 72 bytes contain 32 reserved bytes, a little-endian uint32 trailer
length, a little-endian uint32 version, and the ASCII marker
`8db42d694ccc418790edff439fe026bf`.

Immediately before the footer is `<BBI`: encoding, record kind 0, and index length.
The index itself contains ten-byte `<BBII` entries: kind, encoding, payload size,
and offset from the start of the trailer. Encoding 0 denotes the observed binary
records; encoding 1 denotes the camera metadata protobuf. The reader supports
bounded indexed versions 1/2/3. Earlier non-indexed layouts are not implemented.

The important v3 difference is that indexed payloads can omit the trailing
six-byte record header used in older layouts. Requiring that header caused an
existing parser to skip all useful telemetry. This reader follows the index and
checks bounds, duplicate kinds, overlap and supported metadata encoding. Legacy
indexed records still require consistent trailing headers.

## Records used

- **1:** protobuf camera metadata, including the two-lens calibration and video
  timebase. Only selected field numbers are interpreted. Field 175 (varint) reports
  propeller-guard status: observed enum 0 none, 1 wear, 2 large, 3 dongle. The
  masks require a known matching status; absent values are not assumed zero. Serial/GPS fields are
  not emitted by the inspector.
- **3:** observed raw IMU samples, `<Q6H`, 20 bytes each. Values are unsigned with
  an offset of 32768; ranges are supplied by metadata. Optional per-unit gyro
  calibration/interpolation uses this stream; image timing remains experimental.
- **4:** observed exposure samples, `<Qd`, 16 bytes each: timestamp in microseconds
  and exposure duration in seconds. `inspect` reports statistics without changing
  the calibrated frame clock. See the exposure notes below.
- **32:** embedded frame camera and pilot view; length-prefixed video header and
  120-byte items, or one bare photo item. See the record-32 section below.
- **37:** observed attitude samples, `<Q7f`, 36 bytes each. Timestamp in microseconds,
  an XYZW unit quaternion, and three uninterpreted floats. The approximately
  50 Hz attitude interpretation is supported by sampled image comparisons.

Time is relative to the first video timestamp in metadata. Gyro timing,
rolling-shutter readout and a reference-fitted attitude offset are different
quantities; do not add them indiscriminately. With an explicit schema 1–3 sensor
profile, the renderer uses its measured attitude offset. With `--rolling-shutter auto`, it also uses
embedded sensor readout duration and a locally constant angular velocity by default.
The optional `--rolling-shutter-model trajectory` instead uses 33 uniformly spaced
quaternion samples from the selected orientation trajectory. Each lens uses its own native row; the
inverse center-to-capture rotation is evaluated with two row-map updates.
Quaternion signs are made continuous before normalized linear interpolation.
The explicit sensor path uses recorded attitude; `--gyro-profile` supplies experimental
anchored raw-gyro interpolation. `--rolling-shutter-model velocity` retains the
older constant-rate approximation. Missing readout metadata disables row correction; invalid values
fail preflight.

## Embedded view record 32 and original-only mode

The examined category-0 A1 originals contain both a frame camera orientation and
pilot/main view orientation. Video payloads begin with a little-endian uint32
header byte length (including that length word). Skip that header and read exact
120-byte items. The examined INSPs contain one bare 120-byte item without a header.
The independent reader validates bounds, encoding, monotonic times and unit
quaternions. Other record/category layouts are refused, not guessed.

| Item offset | Type | Current interpretation |
| --- | --- | --- |
| 0 | uint64 LE | Timestamp in microseconds; subtract metadata first-frame timestamp. |
| 8 | float32 LE | Uninterpreted. |
| 12, 16 | two float32 LE | Recorded extent values; observed 100/100, projection/zoom meaning unqualified. |
| 20 | four float32 LE | Embedded camera quaternion, **WXYZ**. |
| 36 | four float32 LE | Pilot/main-view quaternion, **WXYZ**. |
| 52–115 | 64 bytes | Other orientation/tracking fields, not interpreted here. |
| 116 | uint32 LE | View category; only observed category zero is qualified for this reader. |

With `C = Rx(+90°)`, the independently tested coordinate conversion is:

```text
lens0_to_sphere = C * inverse(camera) * C
pilot_camera_to_lens0 = inverse(C) * pilot * inverse(C)
pilot_camera_to_output = rendered_lens0_to_output * pilot_camera_to_lens0
```

Coordinates are x right, y down, z forward. These records use WXYZ storage;
record 37 and the exported sidecar use XYZW. Do not interchange them. Slerp uses
normalized quaternions and shortest arcs; selected interpolation gaps over 250 ms
or uncovered times fail. Original frame index / rational FPS determines the
record-32 query time. Output path time is rebased to the selected first frame.

Without `--calibration`, original-only setup uses this camera orientation and
fits relative lens rotation from up to three original frame pairs. Each candidate
needs at least 30 inliers, 50% inlier support and at most 1.2° p95 angular residual.
At least two candidates and a strict majority must agree within 0.75°. A medoid
selects an observed fit without averaging conflicting geometry. Near file end,
earlier original frames supply the extra samples. Photos use one checked pair.

Schema 4 stores the lens fingerprint, relative rotation, original-only method,
embedded orientation convention and fit evidence. It has no fitted sensor mount
or sensor time offset; those fields are rejected. Camera pose comes from the
original. A fixed source-relative heading is selected, not surveyed compass north.
Raw-sensor row correction is disabled in this mode; raw gyro requires an explicit
schema 1–3 sensor calibration. This is not a new high-rate IMU solution or a claim
that embedded frame orientation has Studio-equivalent smoothing.

Read-only inspection of local Studio data-reading interfaces helped establish
record layout/order. Coordinate hypotheses were checked against original data,
relative motion, independently reference-calibrated vertical and a photo sphere.
No vendor library, disassembly, profile or code is distributed or loaded at runtime.
Compatibility beyond the examined category/layout and camera remains unqualified.

## Guided viewport output

Default `--view pilot` adds `OUTPUT.viewport.json` and `OUTPUT.view.html`. The JSON
has schema 1, kind `a1-pilot-viewport-v1`, `output-presentation-seconds` timebase,
XYZW order (`xyzw`), source first frame/FPS, one camera-to-sphere quaternion per
output frame, and the generated video SHA-256. The receipt hashes both companions.
The HTML embeds that same path and performs WebGL perspective viewing with Slerp,
free look, zoom and a smooth return to follow. `a1-stitch view` verifies companions
before starting a loopback-only, allowlisted byte-range server.

`hfov_degrees: 90` is a presentation choice, not a decoded recording of pilot zoom.
The two source extent values are reported as observations, not assumed to be degrees.
MP4 pixels remain the complete stabilized sphere; no timed OMAF track or fixed
flat crop is written. Standard Spherical Video V2 metadata alone does not play
this path. `--view fixed` suppresses both guided companions.

## JPEG-based INSP and panorama TIFF

The examined A1 INSPs are 8-bit RGB JPEGs with an indexed trailer, a side-by-side
two-fisheye raster and one record-32 orientation. A 2:1 source raster is not already
a stitched sphere. Native JPEG dimensions must match metadata and EXIF orientation
must be absent or one. DNG, non-RGB/non-JPEG and unsupported gamma modes fail.

Photo output is one complete 2:1, RGB16 TIFF page with lossless Deflate. TIFF XMP
tag 700 contains GPano projection/viewer properties, full/cropped dimensions and
zero crop offsets following the [Photo Sphere specification](https://developers.google.com/streetview/spherical-metadata).
An existing ICC profile is copied to tag 34675; none is invented if missing. No
EXIF/GPS or proprietary trailer is copied. Pixel and output checksums, input
identity, fit, color/precision limits and implementation are recorded in a receipt.
Full decompression verifies exact rendered pixels and panorama-tag agreement.

RGB16 preserves interpolation/blend precision. The examined JPEG source is 8-bit;
this output is not 16-bit capture, RAW development, HDR recovery or an EXIF archive.
Panorama TIFF recognition is application-dependent.

## Exposure record 4

The observed A1 encoding-0 layout consists of little-endian uint64 timestamps and
float64 shutter durations. Two recordings contain approximately one sample per
video frame, including samples before video frame zero. Inspection validates
record boundaries, increasing timestamps, finite positive durations and cadence.
Reports include min/median/p95/max duration, gaps, and half the duration range.

Exposure time and sensor readout are different quantities. Schema-1 calibration
keeps nominal frame time plus its fitted offset. Inspection alone therefore
reports `applied_to_frame_clock: false`. Schema 2, created only by refitting with
`calibrate --frame-clock exposure`, uses `exposure-midpoint-v1`: the frame's
record timestamp minus half its shutter duration, then the newly fitted offset.
The recipe reports the active clock. Timestamps are relative to video zero, not UTC.

Two tested sources contain a unique exact first-video timestamp at exposure
index 8. The clock requires that exact anchor and ordinal agreement within
one tenth of a frame for every following sample. Missing samples/drift are
rejected rather than shifting later indices; requested indices must be covered.
Durations must not exceed 1.01 frame periods. The calibrated clock applies to
center pose, heading reference and row correction on CPU/Metal. It is not a
change to output video cadence, and image-timing qualification remains limited.
See [the 0.7 measurements](quality-v0.7.md).

## GPS record 7

The examined A1 v3 trailers contain encoding-0, 53-byte GPS samples. The byte
layout agrees with the public telemetry-parser GPS reader and ExifTool's INSV
GPS field interpretation; only the layout and field meanings inform this
independent implementation. See [NOTICE](../NOTICE) for sources.

| Offset | Type, little-endian | Interpretation |
| --- | --- | --- |
| 0 | uint64 | Unix seconds |
| 8 | uint16 | Fractional milliseconds, 0–999 |
| 10 | char | `A` acquired or `V` void |
| 11 | float64 | Latitude magnitude in degrees |
| 19 | char | `N` or `S` |
| 20 | float64 | Longitude magnitude in degrees |
| 28 | char | `E` or `W`; the publicly observed `O` west variant is also accepted |
| 29 | float64 | Reported speed in m/s |
| 37 | float64 | Reported course in degrees |
| 45 | float64 | Reported altitude in metres; vertical datum unverified |

Coordinates are signed using their hemisphere fields. Longitude +180° is
represented as the equivalent -180° to satisfy GPX 1.1. Latitude/longitude must
be finite and within geographic bounds. Void fixes and invalid positions break
segments; optional nonfinite altitude or invalid speed/course are omitted and
counted. Unknown active-fix layouts, invalid millisecond fields and non-increasing
acquired UTC timestamps fail rather than being reordered or assigned guessed times.
The reader accepts at most 100,000 samples and does not use video decoding.

GPX exports these measurements without geoid correction or altitude smoothing.
Although the observed heights are consistent with an absolute altitude, their
vertical reference has not been established; they are not advertised as surveyed
MSL elevation, height above ground or takeoff-relative height. Course is retained
as reported rather than promoted to a calibrated compass heading. Active status
does not establish satellite count, accuracy, or a 3D fix.

GPX covers the source recording's GPS track, independently of a stitched frame
range. GPS Unix timestamps are distinct from the relative IMU/video clock. A
frame-accurate mapping between those clocks is not yet qualified. Track gaps are
preserved and no intermediate points or coverage outside the source are invented.
The output uses the [GPX 1.1 schema](https://www.topografix.com/GPX/1/1/), with speed,
course, original sample index and status under
`https://github.com/Oceanswave/a1-stitcher/xmlns/flight/1` extensions.

## Geometry

The tested A1 `offset_v3` holds a lens count, 19 values per lens, and a final flag:

```text
xi, fx, fy, cx, cy, yaw, pitch, roll, tx, ty, tz,
k1, k2, k3, p1, p2, combined_sensor_width, sensor_height, lens_type
```

Subtract one sensor width from lens 1's combined-coordinate principal point before
scaling to decoded dimensions. The A1 parameters differ from published experimental
X5 defaults; neither its MEI mirror parameter nor an X5 IMU-axis transform is an
appropriate substitute.

The implementation uses the unified omnidirectional/MEI model with Brown distortion.
A spherical feature fit estimates the relative lens rotation. For advanced sensor processing, a separate reference
fit estimates the camera-to-attitude mounting and time offset from the reference's
vertical. Heading following and creative reframing are independent policies.

The CPU strip renderer or independent Metal kernel maps the output sphere into each lens. The default `flow` seam
mode checks bidirectional optical-flow correspondence in the overlap and applies
bounded local alignment and color matching before blending. The optional
`adaptive` mode also moves the seam along a temporally limited path through areas
of better lens agreement; `feather` retains angular blending without those flow
corrections. These operations do not solve camera translation, severe near-subject
parallax/occlusion. Optional native visibility profiles exclude housing/guard
pixels after row projection and select the other lens when available; they
reject holes instead of reconstructing doubly occluded detail. See the
[current quality evidence](quality-v0.8.md) for measured behavior and limits.

## Output metadata

`st3d` identifies monoscopic video. `sv3d/svhd/proj/prhd/equi` identify a complete
equirectangular sphere with zero additional presentation rotation. The fields
follow the [Spherical Video V2 specification](https://github.com/google/spatial-media/blob/master/docs/spherical-video-v2-rfc.md).

The output contains one newly encoded video track. It does not retain the two
original HEVC lens tracks, `INS.Subtitle` track, indexed trailer, or complete camera
telemetry. The external receipt contains processing provenance and frame mapping,
not a lossless copy of those records. `gpx` or `stitch --export-gpx` can additionally
preserve the decoded GPS track in a separate GPX file. See the
[conversion tradeoffs](../README.md#what-conversion-preserves-and-bakes-in) before
treating an export as an archive.

The renderer first tags its own moov-last MP4. A bounded relocation pass then moves
`moov` forward, shifts `stco/co64` sample offsets and promotes tables to 64 bits if
necessary. This avoids a remux path that dropped spatial metadata in a tested
FFmpeg build. Only this final container relocation copies encoded media bytes
unchanged; the preceding stitch render and H.264 encode are not lossless. The final
file is decoded and inspected before publication. Arbitrary fragmented containers
are not supported.

See [NOTICE](../NOTICE) for public research references and provenance.

## Finishing and motion options in 0.5

Native lens decoding and an 8192-wide sphere are the defaults. HEVC10 and ProRes
paths decode to 16-bit BGR, analyze flow on 8-bit proxies, and retain the 16-bit
signal for final remapping/blending before a 10-bit encode. The H.264 review path
remains 8-bit. Input acceptance still covers only tested 8-bit full-range SDR
BT.709 lens tracks; this does not establish log/HDR support.

Owned ProRes exports convert the encoder's BT.709 `nclc` description to `nclx`
with a zero full-range flag, making the pipeline's limited-range output explicit
to older FFmpeg probes as well. This updates the container only; pixel data is
unchanged. Missing, duplicate or conflicting color descriptions fail closed.

The optional gyro path decodes the observed 20-byte binary record-3 samples
(timestamp, three unsigned accelerometer channels, three unsigned gyro channels),
using the embedded gyro range and offset-binary interpretation. Per-unit rigid
rotation, timing and bias are fitted against low-pass recorded attitude and
validated on another recording. Raw integration is bounded by recorded-attitude
anchors; the default spacing within gyro mode is 0.1 seconds, configurable from
0.02 to 1 second. Long sensor gaps, saturation and unsupported rates fail.
Calibration at low frequency is not proof of high-frequency image timing.

Metal carries the same MEI/Brown geometry, two native-row timing iterations and
confidence-gated seam model. Low-resolution seam analysis remains on CPU. Small
interpolation differences are measured separately from end-to-end throughput.
Native Swift/Metal source participates in the processing fingerprint and ships
inside the wheel; no vendor binary or model is required.

See the README's [source-versus-output importance table](../README.md#what-conversion-preserves-and-bakes-in)
for what remains editable, is baked into pixels, is exported separately or is
unsupported. The video does not retain the raw trailer or sensor streams.

## Image timing and reviewed visibility in 0.8

Calibration schema 3 preserves an explicit `nominal` or `exposure-midpoint-v1`
clock and adds `visual_sync.kind: a1-image-row-sync-v1`, a readout multiplier,
the capture frame rate/readout, base calibration fingerprint, fitted gyro-profile fingerprint and anchor
spacing. Its time shift includes the measured image adjustment. Render preflight
requires the corresponding gyro profile and trajectory row model; older versions
reject the schema rather than silently discarding its readout correction.
The source video cadence is never changed. This is an independent robust
image/trajectory fit, not a decoder for another proprietary timing record.

Native visibility schema 2 adds a review state and `clipping-contrast-v1` alternate
quality policy. Proposals contain original sampled frame indices and input identity.
Unreviewed/empty profiles cannot render. Only forced replacements use dynamic
quality checks; ordinary primary-lens coverage does not require visible texture.
Current clipping rejects immediately; contrast confidence is damped over frames.
The profile and policy are included in receipts and processing identity.

The optional `multiband` seam uses three frequency bands in the existing overlap:
native high-frequency detail plus two confidence-gated low-frequency differences.
Corrections taper inside available support so a narrow overlap does not introduce
an abrupt blend boundary. Unsupported or occluded pixels contribute no correction.
This is a bounded belt implementation, not a full-resolution panorama pyramid or
a reproduction of Studio image fusion. All changes are baked into rendered pixels.

Image timing capture-mode checks require the same exact frame rate and allow
up to 1% readout variation (plus 1 µs numerical tolerance), because embedded
readout measurements differ slightly between same-mode recordings. Larger scan
changes require a new fit. The multiplier still applies to each source
recording's own readout measurement.
