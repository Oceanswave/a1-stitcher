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
  timebase. Only selected field numbers are interpreted. Serial/GPS fields are
  not emitted by the inspector.
- **3:** observed raw IMU samples, `<Q6H`, 20 bytes each. Values are unsigned with
  an offset of 32768; ranges are supplied by metadata. Used for inspection, not
  high-rate stabilization in this release.
- **37:** observed attitude samples, `<Q7f`, 36 bytes each. Timestamp in microseconds,
  an XYZW unit quaternion, and three uninterpreted floats. The approximately
  50 Hz attitude interpretation is supported by sampled image comparisons.

Time is relative to the first video timestamp in metadata. Gyro timing,
rolling-shutter readout and a reference-fitted attitude offset are different
quantities; do not add them indiscriminately. The current renderer uses its
profile's measured attitude offset. With `--rolling-shutter auto`, it also uses
embedded sensor readout duration and the recorded attitude trajectory to correct
native sensor-row timing. This does not use the raw IMU record for high-rate
stabilization. Missing readout metadata disables row correction; invalid values
fail preflight.

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
A spherical feature fit estimates the relative lens rotation. A separate reference
fit estimates the camera-to-attitude mounting and time offset from the reference's
vertical. Heading following and creative reframing are independent policies.

A strip renderer maps the output sphere into each lens. The default `flow` seam
mode checks bidirectional optical-flow correspondence in the overlap and applies
bounded local alignment and color matching before blending. The optional
`adaptive` mode also moves the seam along a temporally limited path through areas
of better lens agreement; `feather` retains angular blending without those flow
corrections. These operations do not solve camera translation, severe near-subject
parallax/occlusion, or propeller/body removal. See the
[current quality evidence](quality-v0.3.md) for measured behavior and limits.

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
