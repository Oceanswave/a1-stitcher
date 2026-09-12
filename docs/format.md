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
profile's measured attitude offset and does not perform per-row correction.

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

A strip renderer maps the output sphere into each lens, then uses angular feather
weights in the overlap. It does not solve camera translation, near-subject parallax,
optical-flow seams, exposure matching, or propeller/body removal.

## Output metadata

`st3d` identifies monoscopic video. `sv3d/svhd/proj/prhd/equi` identify a complete
equirectangular sphere with zero additional presentation rotation. The fields
follow the [Spherical Video V2 specification](https://github.com/google/spatial-media/blob/master/docs/spherical-video-v2-rfc.md).

The renderer first tags its own moov-last MP4. A bounded relocation pass then moves
`moov` forward, shifts `stco/co64` sample offsets and promotes tables to 64 bits if
necessary. This avoids a remux path that dropped spatial metadata in a tested
FFmpeg build. Media bytes are copied unchanged, and the final file is decoded
and inspected before publication. Arbitrary fragmented containers are not supported.

See [NOTICE](../NOTICE) for public research references and provenance.
