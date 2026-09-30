# A1 Stitcher

Independent **Antigravity A1 → equirectangular video and RGB16 TIFF** conversion,
with a command line for batch work and agents.

Export supported originals **without Antigravity Studio, a reference export, or a
manual calibration step**. The CLI reads embedded lens geometry and camera
orientation, checks alignment against the original lens overlap, renders a full
sphere, and verifies the result. Pilot-follow viewing is the default: video exports
include a timed quaternion path and a local interactive player. Use `--view fixed`
to export just the stabilized sphere and receipt.

**Status: alpha. Version 0.9.0 adds original-only setup, guided pilot
viewing and 16-bit panorama TIFFs.** Video defaults remain 8192×4096, native lens
frames, 16-bit processing, 10-bit HEVC, checked flow seams and automatic Metal on
supported Macs. The portable CPU renderer remains available. Original-only mode
uses the embedded camera orientation; advanced raw-gyro, exposure-timing and
sensor-row correction still require an explicit sensor calibration. These are
separate processing modes, not equivalent stabilization claims.

The generated MP4 remains a complete, stabilized sphere. **The companion viewer
follows the pilot; ordinary players do not automatically consume the JSON path.**
Recorded pilot zoom is not yet qualified, so guided presentation starts at a 90°
horizontal field of view. Studio project edits, tracking modes, proprietary
FlowState/AI stitching and exact playback parity are not reproduced.

Earlier tools remain available: image/gyro synchronization with temporal holdouts,
reviewed obstruction proposals, native visibility masks, multiband seams, GPX,
and source-matched Studio comparisons. Masks use the other real lens where it
sees the scene; they cannot reconstruct detail blocked in both lenses. Close
parallax, flare, fast motion, blade blur and broader A1 recording-mode/firmware qualification
remain open. See [0.9 validation and limits](docs/quality-v0.9.md),
[0.8 timing evidence](docs/quality-v0.8.md) and
[measured Metal performance](docs/quality-v0.5.md).

See the [A1 recording-mode coverage](docs/recording-modes.md) and
[development priorities](docs/roadmap.md). Standard SDR video and JPEG-based INSP
are the tested paths. Slow motion, timelapse, DNG and grouped HDR/AEB/burst photo
processing remain incomplete. The development version reports mode declarations
and rejects unqualified retimed captures before rendering; these checks are
listed under **Unreleased** in the changelog, not part of the 0.9.0 release.

This is an independent implementation, not an official Antigravity or Insta360 product.

## What conversion preserves and bakes in

**Keep the INSV/INSP originals. Exported video and TIFFs are rendered 360° working copies,
not replacements for the camera recording.** Conversion never modifies the
original. INSV is already an MP4-family container; this process decodes its two
fisheye tracks, renders a sphere, and encodes new pixels. Renaming or remuxing the
original would not perform that work.

Importance describes the practical effect on future editing: **High** means an
important capability requires the originals or the input is unsupported;
**Medium** means a quality or workflow tradeoff to plan around; **Low** means
little loss for ordinary editing when the generated files are interpreted correctly.
Conditional ratings apply only to the stated use. These are workflow judgments,
not measured image-quality scores.

| Area | What the CLI generates or preserves | Difference from the source archive | Importance and practical effect |
| --- | --- | --- | --- |
| Re-stitching and lens geometry | One full equirectangular sphere, rendered from both calibrated lens tracks. | Dewarp, lens registration, seam decisions, flow, local color matching and optional three-band blending are baked into pixels. Separate fisheye images and overlap cannot be recovered from the composite. | **High** — keep INSV to improve stitching, change calibration, handle parallax differently or use a future vendor algorithm. |
| Stabilization and rolling shutter | Original-only mode uses embedded frame orientation and a source-relative heading. Explicit sensor profiles retain recorded-attitude, exposure/gyro timing and native-row correction. Further sphere rotation remains possible. | Applied corrections are baked in. Raw IMU, original attitude samples and sensor-row measurements are not embedded in the generated video. The gyro profile in the receipt describes processing; it is not the raw sensor stream. | **High** — original-only mode does not apply raw-sensor row corrections. Re-running sensor stabilization or changing timing requires the original and an appropriate profile; the exported sphere can still be reframed. |
| View, framing and depth | Complete 360° × 180° monoscopic coverage, with later yaw/pitch/roll, field of view, tracking and animated reframes. | No stereo depth or change of the physical viewpoint is created. This is a capture limit, not something equirectangular export discards. | **Low** for ordinary reframing — the full sphere is retained. An overhead drone cannot become a ground-level camera through reframing. |
| Pilot viewpoint | Default `--view pilot` writes a presentation-timed quaternion JSON and guided HTML player, bound to the video checksum. `--view fixed` opts out. | Pilot direction can be replayed without Studio. Zoom uses an explicit 90° presentation default; proprietary tracking/edit controls are not reconstructed. The MP4 alone contains no universally supported timed-view instruction. | **Medium** for guided sharing — keep the companion files and use `a1-stitch view`; **High** for exact Studio viewport/zoom equivalence, which remains unqualified. |
| Original-only setup | Embedded camera pose plus a checked majority of original overlap fits; fitted geometry and evidence are stored in the receipt. | No vendor reference or manually supplied mount profile is needed on supported record-32/category-0 originals. Low texture, inconsistent fits and unknown layouts fail explicitly. This does not estimate a new high-rate sensor calibration. | **Low** workflow loss for supported files; **High** where advanced row timing or unsupported capture modes are needed. Keep originals for improved processing. |
| Still photos | JPEG-based A1 INSP → native-width RGB16 TIFF, lossless Deflate, XMP tag 700 with GPano equirectangular/full-sphere dimensions; available ICC preserved. | The tested source is 8-bit. Sixteen-bit interpolation reduces new rounding; it is not RAW development or added captured dynamic range. EXIF/GPS and vendor trailer remain only in the original. DNG is unsupported; TIFF panorama recognition depends on the receiving app. | **Medium** for photo grading and sharing; **High** for RAW or camera metadata reprocessing. Keep INSP/DNG originals. |
| Spatial detail and compression | Default 8192×4096 output from native-size lenses; optional ProRes 422 HQ or smaller review encodes. | Projection interpolation, seam blending and another lossy encode change pixels. Native-resolution processing avoids the former 1440-pixel lens downsample; an 8K sphere does not imply 8K detail in a narrow reframe. | **Medium** at the new defaults; **High if a small preview is used for finishing**. Render a fresh master from INSV when changing quality settings. |
| Color precision and chroma | Default 16-bit image processing → 10-bit 4:2:0 HEVC, CRF 12. ProRes 422 HQ offers 10-bit 4:2:2; H.264 review mode uses 8-bit 4:2:0. | The tested original is 8-bit 4:2:0 SDR. Extra processing precision reduces new rounding but does not create captured dynamic range or missing color detail. HEVC and ProRes are still lossy generations. | **Medium** for grading — use HEVC10 or ProRes and avoid repeated intermediate re-encodes. This fixes the old always-8-bit output limitation, not the source's capture limits. |
| Color space, range and log/HDR | Tagged limited-range SDR BT.709 suitable for SDR Resolve/Fusion grading. No LUT is applied. | Tested sources are full-range SDR BT.709. The range conversion changes signal encoding, not intended display contrast when interpreted correctly. Log/HDR/higher-bit-depth inputs remain rejected. | **Low** for correctly interpreted supported SDR; **High if log/HDR ingest is required** — it is unsupported, not silently flattened. |
| Exposure telemetry and synchronization | `inspect` reports shutter/timestamp statistics. Optional schema-2 calibration fits an exposure-midpoint attitude clock. Schema 3 can refine image/gyro offset and row readout jointly; dependencies and timing are recorded. | Raw exposure samples are not copied into MP4. The chosen timing is baked into stabilization, while output cadence stays unchanged. Image fits must pass temporal holdouts; they can reject an unhelpful result and do not establish transfer automatically. | **High** for future sensor reprocessing; **Low** for routine cutting. Keep INSV and refit with `calibrate --frame-clock exposure`; never append a guessed offset to an old profile. |
| Camera/propeller visibility | Optional camera/accessory-bound native masks select visible pixels from the other real lens; the profile is stored in the receipt. | Lens selection is baked into the composite. Authored masks or reviewed multi-frame proposals guide exclusion; this is not complete blade segmentation or reconstruction of doubly occluded detail. Schema-2 masks check alternate-lens clipping/contrast during forced replacement. Broad masks can worsen flare or seams; unavailable replacements fail. | **High when the aircraft intrudes**; **Low when the default seam already avoids it**. Keep originals to revise the profile and inspect moving boundaries. |
| Frame timing and selected duration | Selected consecutive frames at the original constant frame rate, with exact first-source-frame/count in the receipt. | Unselected frames are absent from this working copy. No retiming or frame interpolation is added by stitching. | **Medium** — include handles; the archive is needed for longer trims or a different event. |
| Audio | Typical tested A1 inputs have no audio track. | Inputs containing audio are refused; this release has no audio-preserving conversion path. | **High if the input contains sound** — conversion is blocked rather than silently dropping it. Keep any separate sound recordings for the editor. |
| GPS flight profile | Optional GPX sidecar with recorded position, UTC, reported elevation and speed/course extensions; checksum in the video receipt. Standalone extraction is also available. | GPS is not embedded as the original telemetry track. GPX covers the entire source recording, even for a short video selection. Exact UTC/video alignment and altitude datum remain unqualified; missing/invalid GPS causes the requested export to fail. | **Medium** for editorial maps; **High for precise flight/sensor analysis**. Keep originals and the sidecar; do not treat reported elevation as verified AGL or infer a complete multi-file flight. |
| Other camera data and Studio controls | Standard sphere/stereo tags plus a receipt containing source identity, frame mapping, profiles, versions, backend and output checksum. | Other telemetry/subtitle tracks, the vendor trailer, raw sensor records and proprietary project/edit controls are not copied. This does not reproduce FlowState/AI stitching, automatic aircraft removal or all Studio behaviors. | **High** for future camera-specific reprocessing; **Medium** for everyday editing. Neither receipt nor GPX is a complete metadata archive. |
| Container and editor interoperability | Standard MP4 (HEVC/H.264) or MOV (ProRes), fast-start layout and Spherical Video V2 metadata. | INSV was already an MP4-family container, but with separate lens tracks and proprietary data. Conversion adds a usable sphere; renaming/remuxing alone cannot. A 360-aware editor is still needed for reframing. | **Low** loss and a substantial interoperability gain. The original and the generated sphere serve different purposes. |
| CPU versus Metal | The same calibrated projection, seam and row-correction models; chosen backend is recorded. | Small numeric/interpolation differences remain between implementations. GPU speed does not add source detail, restore blur or alter which metadata is preserved. | **Low** on qualified comparisons — choose automatic Metal for speed or CPU for the reference path; neither removes the need for motion review. |

Archive untouched INSV/INSP files and any explicit lens/gyro profiles alongside
output receipts. Keep viewport JSON/HTML and GPX when exported and preserve source-frame mappings for
reference media. The generated MP4/MOV/TIFF and sidecars are working derivatives,
not a reversible replacement for the source archive.

### A 4K sphere is not a 4K reframed shot

The sphere's width covers **all 360°**. At the equator, a 90° horizontal view
spans roughly 512 source columns in a 2048-wide sphere, 1024 in a 4096-wide sphere,
or 2048 in an 8192-wide sphere. This is an angular-sampling guide, not a guarantee
of rectilinear output detail: projection, lens quality and sampling vary across
the image. The default `--width 8192 --lens-width 0` retains native lens resolution
and the full supported sphere size. Zero means native; upscaling the decoded
lenses beyond their source size is refused. For a smaller review use explicit
`--width 2048 --lens-width 1440 --encoding h264`. Real 8K sequences have passed
full decode and source-matched comparisons, but that does not qualify every
shot, camera or scene for finishing.

### Which limits can improve?

Equirectangular describes the projection, and MP4/MOV the container. Neither
requires 8-bit H.264. This release implements higher-precision processing,
10-bit HEVC and ProRes working codecs, plus optional GPX sidecars. Higher precision
reduces additional processing loss; it does not invent detail or dynamic range
missing from an 8-bit recording. Limited-range BT.709 is a signal encoding choice,
not by itself a narrower display brightness range when interpreted correctly.

Seams, propeller visibility, severe parallax and residual vibration are also
algorithm/capture limitations, not inherent consequences of equirectangular MP4.
Studio comparisons help evaluate those differences. Even a better stitch remains
a rendered composite once exported.

Archive the untouched INSV plus the calibration profile and receipt. Use the
sphere for editing, grade it as the tagged SDR BT.709 material it is, and render
again from the original when improving stitching or preparing a higher-quality
finish. Avoid repeated intermediate re-encodes. See [format notes](docs/format.md)
for the source records and output metadata.

## Install

Python 3.12+, macOS or Linux, and FFmpeg/ffprobe are required. The default
needs HEVC decoding and `libx265`; previews use `libx264` and ProRes uses
`prores_ks`. Metal additionally needs a usable macOS GPU and Swift command line tools. Install FFmpeg separately using your normal package manager.

```sh
# From a checkout
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/a1-stitch doctor

# Or install the tagged source as an isolated CLI with uv
uv tool install 'git+https://github.com/Oceanswave/a1-stitcher.git@v0.9.0'
a1-stitch doctor
```

No PyPI publication is implied by the package name. No vendor SDK, downloaded
binary, cloud service, network connection, or license key is needed at runtime.

## Workflow

```sh
a1-stitch inspect recording.insv --output inspection.json
```

Inspection reads bounded trailer records and reports camera, calibration and
motion metadata. Camera serial numbers and GPS fields are not decoded into the
report; use `--redact-path` when sharing it. Reports and receipts can still reveal
filenames or local paths. Review them before posting publicly.

### Export directly from the original

```sh
# No calibration file or Studio export is needed on supported originals
a1-stitch stitch recording.insv --first-frame 1200 --frames 360 --output sphere.mp4

# Follow the recorded pilot direction; drag to take control
a1-stitch view sphere.mp4

# Opt out of guided viewing; keep the stabilized full sphere
a1-stitch stitch recording.insv --first-frame 1200 --frames 360 \
  --view fixed --output fixed-sphere.mp4
```

Automatic setup uses up to three original frame pairs. At least two overlap fits
must agree within 0.75°; poorly textured or inconsistent intervals fail with an
explanation. Try a better interval or supply a qualified `--calibration` profile.
Video records must cover the selected range without interpolating gaps over 250 ms.
The supported embedded view layout/category is checked rather than guessed.

The receipt records the original-only schema-4 fit. No reusable camera profile
needs to be created beforehand. This mode uses processed frame orientation and
disables raw-sensor row correction; `--gyro-profile` requires an explicit schema
1–3 sensor calibration. It is not calibrated compass north or a claim of
FlowState-equivalent stabilization. Review actual moving shots.

### Pilot-follow playback

`--view pilot` is the default for both automatic and explicit-profile stitching.
It writes `sphere.mp4.viewport.json` and `sphere.mp4.view.html` alongside the video
and receipt. The same convention applies to MOV outputs. `a1-stitch view VIDEO
--port 8778` verifies their checksums and serves only that movie and viewer on
localhost. Use a browser-compatible video encode; H.264 is suitable for small
reviews, while browser HEVC/ProRes support varies.

The path preserves source-frame mapping and uses output presentation seconds,
normalized XYZW camera-to-sphere quaternions and shortest-path spherical
interpolation. Trimming an original does not leave a time offset in playback.
The player defaults to pilot follow; drag/free-look overrides it and Follow pilot
returns smoothly. Scrolling adjusts presentation zoom.

The sphere pixels stay available for later reframing. An ordinary 360 player
can open the MP4 but does not automatically follow this sidecar. Spherical Video
V2 tags describe the sphere; they do not implement our timed camera path. Timed
OMAF metadata and baked flat reframes are not implemented here. The HTML embeds
the path at export; editing JSON alone does not update the player, and modified
companions fail receipt checks. Recorded zoom/projection controls remain
unqualified; the player starts at 90° horizontal FOV.

### Export a 360 photo

```sh
a1-stitch photo capture.insp --output panorama.tiff
a1-stitch verify-photo panorama.tiff --receipt panorama.tiff.receipt.json
```

Supported JPEG-based two-lens A1 INSP originals are stitched directly, with no
Studio or manual calibration. Default width matches the input raster (7680 in
the examined originals), height is half the width, and RGB has 16 bits per
channel with lossless Deflate compression. `--width` allows smaller multiples of
four; upscaling is refused. `--backend auto|cpu|metal`,
`--seam flow|multiband|feather`, `--calibration`, `--dry-run` and `--resume` are
available. A supplied profile must match the embedded lens fingerprint; only its
relative lens alignment is used for photos.

TIFF tag 700 contains [Photo Sphere XMP](https://developers.google.com/streetview/spherical-metadata):
`GPano:ProjectionType=equirectangular`, `UsePanoramaViewer=True`, full and cropped
panorama dimensions, and zero crop offsets. Available ICC is preserved; absent
ICC does not cause an invented color-space profile. Original EXIF/GPS and vendor
metadata remain in the source. Panorama-aware TIFF support varies by application.

This is **16-bit output from an 8-bit rendered photo**, not 16-bit capture, DNG
processing or HDR recovery. Verification decompresses every pixel and checks RGB
precision, dimensions, XMP consistency and checksums. It does not certify seam
quality; inspect the full sphere, horizon, near objects and flare.

### Export the flight track

```sh
# Extract GPS without stitching, calibration, Studio or FFmpeg
a1-stitch gpx recording.insv --output flight.gpx

# Inspect the GPS summary without writing any output
a1-stitch gpx recording.insv --output flight.gpx --dry-run

# Reuse only an identical GPX with a matching receipt and checksum
a1-stitch gpx recording.insv --output flight.gpx --resume
```

The GPX 1.1 track contains recorded latitude/longitude, UTC timestamps with
millisecond precision, and camera-reported elevation in metres. Speed in m/s,
course in degrees, active-fix status and the original GPS sample index are stored
in the `a1` extension namespace; readers may ignore these extensions. No 2D/3D
fix quality is inferred from an active fix. The altitude datum is unverified:
do not treat it as height above ground or takeoff-relative height.

Extraction currently supports the observed 53-byte binary GPS record 7 layout.
Void fixes and invalid positions are omitted, starting a new segment so the
track does not bridge them. Time gaps greater than ten seconds also start a new
segment (`gpx --gap-seconds SECONDS` changes that threshold). Duplicate/backward
acquired timestamps, unsupported layouts and incomplete records fail. No GPS or
no usable fixes produces an error and no GPX. No positions are interpolated.

**The track covers GPS recorded in the entire source file**, even when a stitched
video uses only selected frames. It is not necessarily the entire flight if
recording started late or spanned multiple files. GPS uses its recorded UTC clock;
this release does not assert frame-accurate GPS-to-video synchronization or infer
UTC from filenames. The two examined A1 recordings contained 398 and 549 acquired
fixes at approximately 1.6-second intervals; this is not a guaranteed camera rate.

The standalone command writes `flight.gpx.receipt.json` with source identity,
GPS-record/output checksums, accepted/skipped sample counts and interpretation
limits. Existing outputs and symlinks are refused. GPX files contain actual
locations; `inspect --redact-path` does not anonymize a GPX track.

To export alongside video, add `--export-gpx` to `stitch` or `"export_gpx": true`
to a batch job:

```sh
a1-stitch stitch recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 360 --output selected-sphere.mp4 --export-gpx
```

This also writes `selected-sphere.mp4.gpx`. Its checksum and GPS summary are in
the MP4's receipt; there is no additional GPX receipt in this mode. GPS preflight
runs before rendering, and a successful combined job requires both outputs.
`--resume` checks both checksums. Export is opt-in so sources without GPS remain
stitchable. See [GPS format notes](docs/format.md#gps-record-7) for field meanings.

### Optional advanced sensor calibration

For the advanced raw-sensor stabilization path, supply an existing **full 2:1 stitched equirectangular reference** from the same
original, with known source frame mapping. The reference is used to estimate
mounting/time alignment; its pixels are never used in subsequent conversions.
Use an interval with visible texture and varied camera tilt. A flat reframed
video is not a suitable reference.

```sh
a1-stitch calibrate recording.insv \
  --reference reference-sphere.mp4 --first-source-frame 3000 \
  --samples 0,15,30,60,120,240,480 --holdouts 600,900 \
  --output camera-calibration.json --evidence-dir calibration-review
```

`--first-source-frame` maps reference frame zero to the original. Sample and
holdout numbers are **reference frame indices**. Adjust them to fit the actual
reference interval. Inspect the holdout errors and paired evidence; a low
sampled error is not complete motion/seam acceptance. The profile is bound to
the fingerprint of the embedded lens parameters. Another camera must supply
its own profile.

### Convert selected original frames

```sh
a1-stitch stitch recording.insv \
  --first-frame 1200 --frames 360 \
  --output selected-sphere.mp4
```

Frames use the original's frame rate; `--frames` is a count, not an inclusive end.
Defaults prioritize finishing quality: **8K, native lens frames, 16-bit image
processing and 10-bit HEVC MP4**. `--backend auto` selects Metal when its compiler
and GPU preflight succeed, otherwise records a CPU fallback. `--backend metal`
requires GPU availability; `--backend cpu` selects the portable reference.
The shader uses the same projection, row timing, flow and blending model with
small interpolation differences. Auto selection never reduces resolution or
changes the encoding/seam choice.

```sh
# ProRes 422 HQ MOV for an editing intermediate
a1-stitch stitch recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 360 --encoding prores --output selected-sphere.mov

# Explicit lightweight review, preserving finishing defaults for ordinary jobs
a1-stitch stitch recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 90 --width 2048 --lens-width 1440 \
  --encoding h264 --output preview.mp4
```

All outputs carry limited-range SDR BT.709 tags, monoscopic Spherical Video V2
metadata and fast-start layout. The tested originals are 8-bit full-range SDR
BT.709. Unknown/log/HDR/higher-bit-depth inputs are rejected rather than silently
flattened. No LUT is applied. Audio-containing sources are refused instead of
dropping sound. ProRes output needs a `.mov` suffix; HEVC/H.264 require `.mp4`.

The default `--seam flow` uses bidirectional overlap correspondence, rejects
unreliable/oversized displacement, and matches local color without brightening
the cleaner lens. It samples the original lenses directly at the output's
resolution. `--rolling-shutter auto` uses the embedded readout duration and
an average angular velocity to correct each native sensor row (the qualified
`--rolling-shutter-model velocity` default). The experimental `trajectory` option
uses 33 quaternion samples through the scan and follows changing rotation,
including an optional calibrated gyro trajectory. It improves synthetic changing
motion but gave mixed real-footage results; see the [0.6 report](docs/quality-v0.6.md). Missing readout
metadata disables that correction; invalid values fail preflight. For controlled
comparisons or difficult footage, `--seam feather --rolling-shutter off` retains
the original geometric/blending path. Both choices participate in cache identity.
These corrections cannot recover occluded detail
or remove motion blur. Review the intended shot in motion.

`--heading-reference-frame 0` fixes panorama heading from original frame zero,
even when exporting later ranges. All chunks from one source can use the same
reference. Choose another covered source frame when needed; `-1` restores the
previous selected-clip-start convention. This is a fixed yaw reference, not a
claim of compass north or an automatic subject-following camera. Heading and
row-model choices are recorded in receipts and affect resume identity.

`--seam adaptive` adds experimental seam placement within ±4° of the optical
seam. It seeks a closed path through areas of better lens agreement and limits
path movement to 6°/second. It can avoid some difficult overlaps but does not
identify or remove a camera body, recover hidden detail, or guarantee improvement.
The default remains `flow`. Compare both modes on the intended shot.

### Exposure-aware synchronization and camera visibility

The new options are explicit because their benefit depends on the source.
Create a **new** calibration with `calibrate --frame-clock exposure` using the
same source-matched Studio reference procedure above. The resulting schema-2
profile controls exposure-midpoint queries automatically during stitching;
normal schema-1 profiles retain nominal timing. Do not manually relabel a profile.
The exposure clock leaves output frame rate and color unchanged.

```sh
a1-stitch mask-template recording.insv --output visibility.json
# Edit the template using observed native housing/guard outlines, then inspect it:
a1-stitch mask-preview recording.insv --occlusion-profile visibility.json \
  --frame 300 --output-dir visibility-review

a1-stitch stitch recording.insv --calibration calibration.json \
  --occlusion-profile visibility.json --first-frame 300 --frames 180 \
  --output masked-sphere.mp4
```

An empty mask template is rejected for rendering. Native-image polygons use
normalized x/y coordinates, with lens 0 and lens 1 kept separate. Profiles check
both embedded lens identity and recorded guard configuration. The renderer
uses actual pixels from the other lens and fails if both are unavailable.
There is no automatic blade detector or invented fill. Read the
[profile instructions](skills/stitch-a1-video/references/options.md#exposure-and-visibility-profiles)
and [measured results](docs/quality-v0.7.md) before choosing these options.

### Metal performance

On an Apple M1 Max (32-core GPU, 64 GB), Metal substantially reduces the
stitching stage's cost while retaining native lens precision:

| Sphere size | CPU | Metal | Stitch-stage speedup |
| --- | ---: | ---: | ---: |
| 2048×1024 | 1.050 s/frame | 0.206 s/frame | **5.1×** |
| 4096×2048 | 4.012 s/frame | 0.290 s/frame | **13.8×** |
| 8192×4096 | 13.761 s/frame | 0.444 s/frame | **31.0×** |

Same cached 3840-pixel lens pair, 16-bit processing, flow seams, sensor-row
correction and four CPU threads; median of two warm runs after one warm-up.
These measurements include seam analysis and transfers, but exclude video decode,
encode, startup and verification. They are not whole-export speedups.

For an identical three-frame **complete 8K ProRes job**, external wall time was
**35.73 seconds CPU versus 9.34 seconds Metal—3.8× faster** including startup and
full verification. A separate 90-frame Metal job took 74.17 seconds. Short jobs
have substantial fixed overhead; codecs, storage and scene content change total
time. Real-time 8K export is not claimed.

CPU/Metal differences averaged about 0.12 of an 8-bit channel level in the
unencoded comparison, with the same geometry and processing model. Use
`--backend auto` (default), `--backend metal` to require it, or `--backend cpu`
for the reference path. See [the full methods, pixel differences and motion
results](docs/quality-v0.5.md), [the 0.6 motion pass](docs/quality-v0.6.md), and
[remaining Studio functionality](docs/studio-parity.md) for the measured scope and remaining limitations.

### Optional raw-gyro interpolation

```sh
a1-stitch gyro-calibrate recording-a.insv --validation-source recording-b.insv \
  --output gyro-profile.json
a1-stitch stitch recording-b.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 90 --gyro-profile gyro-profile.json \
  --output gyro-test.mp4
```

Use different recordings from the same unit. The fit checks three-axis excitation,
proper rotation, timing, bias, held-out motion blocks and transfer to the second
recording. Interpolation integrates raw gyro at up to 1 ms steps and matches
recorded-attitude anchors, bounding drift. `--gyro-anchor-seconds` defaults to
0.1 (10 Hz anchors) within this optional mode; 0.02 uses every recorded anchor.
The supported interval is 0.02–1 second. Wider spacing can avoid reintroducing
recorded-attitude jitter, at the cost of allowing more drift between anchors. The profile remains
experimental: low-pass agreement and synthetic vibration tests do not establish
high-frequency sensor-to-image timing. Compare real moving footage before use.

### Image timing, obstruction proposals and multiscale seams

```sh
# Fit sensor/image timing and native-row readout together on a varied interval.
a1-stitch sync-calibrate recording.insv --calibration exposure-calibration.json \
  --gyro-profile gyro-profile.json --first-frame 1200 --frames 600 \
  --output image-calibration.json --evidence-dir timing-evidence

# Only if the fit qualifies: preserve its gyro profile, anchor spacing and row model.
a1-stitch stitch recording.insv --calibration image-calibration.json \
  --gyro-profile gyro-profile.json --rolling-shutter-model trajectory \
  --first-frame 1200 --frames 600 --output timing-test.mp4

# Propose native obstructions from multiple frames; inspect generated overlays.
a1-stitch mask-propose recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 600 --samples 24 \
  --output proposed-mask.json --evidence-dir mask-evidence

# After inspecting/refining actual native exclusions, record that review.
a1-stitch mask-approve proposed-mask.json --output reviewed-mask.json \
  --review-notes "Describe the frames reviewed, retained exclusions and remaining limits."

a1-stitch stitch recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 600 --occlusion-profile reviewed-mask.json \
  --seam multiband --output seam-test.mp4
```

`sync-calibrate` fits a ±40 ms timing adjustment and 0.5–1.5× readout scale.
It uses native-image feature tracks, four contiguous temporal blocks, robust
fitting and observability/boundary checks. A rejected fit writes evidence and
returns JSON `status: rejected`, with **no calibration output**. Exit zero means
the analysis completed; automation must inspect status. A qualifying schema-3
profile requires the same frame-rate/readout mode, gyro-profile fingerprint and anchor spacing, plus
`--rolling-shutter-model trajectory`. It preserves the base nominal or exposure
clock. Do not manually relabel a schema-1/2 calibration or discard these dependencies.
Validate a separate recording before treating a local fit as transferable.

`mask-propose` finds persistent dark, textured mismatches in the native overlap.
It excludes the black image rim and abstains on insufficient scene movement.
Proposals can be incomplete or wrong, and cannot be used by `stitch` until
reviewed. Empty proposals cannot be approved. Schema-2 visibility profiles add
clipping/contrast checks only when a mask forces replacement by the other lens;
if neither view is usable the job fails. This check is not a general flare,
blur or object-identity classifier. Legacy authored schema-1 masks remain supported.

`--seam multiband` retains native detail at a narrow transition, blends two
lower-frequency difference bands over wider transitions, and limits per-frame
color-gain changes. It uses bounded overlap analysis on CPU and the same final
CPU/Metal projection paths. It does not average image pixels across time or
invent occluded detail. All three new processing options remain explicit:
newer algorithms do not automatically beat the established defaults on every shot.
See the [option reference](skills/stitch-a1-video/references/options.md) for limits.

### Receipts and repeated jobs

A matching `.mp4.receipt.json` (or `.mov.receipt.json`) records source range, camera profile, processing
versions, source identity, output SHA-256, coverage, timing and full-decode
verification. Original files are never modified. Existing outputs, receipts,
and symlinks are not overwritten. Failed jobs clean their private work directory;
`--keep-work` retains it for debugging. A lock protects against competing writers.
After an interrupted process, inspect the lock's PID before removing a stale lock.

```sh
# Preflight without creating output files
a1-stitch stitch recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 360 --output selected-sphere.mp4 --dry-run

# Reuse only an identical completed job with a matching checksum
a1-stitch stitch recording.insv --calibration camera-calibration.json \
  --first-frame 1200 --frames 360 --output selected-sphere.mp4 --resume

a1-stitch verify selected-sphere.mp4 --receipt selected-sphere.mp4.receipt.json
```

Resume is **completed-job reuse**, not continuation of a partially encoded file.
Source identity uses file stat plus first/last MiB hashes; it is not a full
cryptographic hash of the original recording. Changed source stat, edge content,
calibration, media settings, package version or FFmpeg version invalidates reuse.

Development batches reuse the initial overlap alignment in memory and recheck
each source before rendering. This removes duplicate fitting without creating a
persistent media cache. Intermediate files are removed unless `--keep-work` was
explicitly requested; receipts and requested companions stay with the output.

### Compare with a Studio export

Use a full equirectangular reference with known source-frame mapping. Both inputs
must have the same constant frame rate. If candidate frame zero corresponds to
reference frame 570, for example:

```sh
a1-stitch compare selected-sphere.mp4 --reference studio-sphere.mp4 \
  --reference-first-frame 570 --samples 0,15,30,60,89 \
  --output-dir new-comparison
```

Open `new-comparison/review.html`. It shows the reference, the candidate after one
global orientation alignment, and its original orientation. The JSON report
preserves frame mapping, input identities, fitted rotations and matched-inlier
angular errors. No local warp or color fit is applied. Per-frame alignment can
hide stabilization differences; inspect the original view, rotation changes and
full motion as well. Low inlier error does not score unmatched/occluded pixels,
prove freshness or certify a whole shot. Existing output directories are refused.

For a continuous motion comparison, use the original frame mapping and a longer
interval (600 frames is about 20 seconds at the tested frame rate):

```sh
a1-stitch benchmark selected-sphere.mp4 --reference studio-sphere.mp4 \
  --reference-first-frame 570 --frames 600 --output-dir moving-comparison
```

This generates a side-by-side video containing six fixed 90° views per input,
with **one alignment on frame zero**. Every decoded frame is included; motion
measurements mark failed tracking rather than bridging missing observations.
The JSON separates angular acceleration, local residuals, brightness changes and
coverage. These are reduced-resolution diagnostics, influenced by scene movement
and parallax. There is no single quality score, absolute horizon measurement or
automatic human-review claim. Inspect native seams and the complete motion separately.

### Batch and agent use

```json
{
  "schema_version": 1,
  "jobs": [
    {
      "source": "recording.insv",
      "calibration": "camera-calibration.json",
      "first_frame": 1200,
      "frames": 360,
      "width": 8192,
      "lens_width": 0,
      "encoding": "hevc10",
      "backend": "auto",
      "output": "prepared/shot-01.mp4"
    }
  ]
}
```

```sh
a1-stitch batch jobs.json --dry-run
a1-stitch batch jobs.json --resume
```

Relative batch paths resolve against the manifest's directory. All jobs are
preflighted before rendering. Jobs run sequentially to keep decoder/GPU/memory
contention predictable. JSON results go to stdout; progress and errors are JSON
lines on stderr. Exit codes are 0 success, 1 processing/input failure, 2 CLI usage
error, and 130 interruption.

The discoverable skill is [stitch-a1-video](skills/stitch-a1-video/SKILL.md).
Copy that folder into your agent's skill directory (for Codex,
`~/.codex/skills/stitch-a1-video`) after checking that it will not overwrite an
existing skill. It uses the installed `a1-stitch` CLI and does not depend on a
particular editing workspace.

### Finish in your editor

Import the sphere into a 360-aware reframe workflow, such as a Fusion spherical
camera in Resolve. Keep virtual-camera movement separate from camera attitude
correction. Match source profiles before grading. Inspect horizons, nearby seam
crossings, vehicle shapes and the entire intended shot in motion before accepting
it as a production master. A valid encode or a stabilization score cannot make a
weak scene compelling.

## Development and evidence

```sh
pip install -e '.[dev]'
pytest --cov=a1_stitcher --cov-report=term-missing
ruff check .
ruff format --check .
python -m build
```

Tests generate synthetic camera containers and synthetic imagery at runtime.
No personal footage, camera profiles, vendor binaries, or proprietary SDK code
are included. See [format notes](docs/format.md), [qualification](docs/qualification.md),
[contributing](CONTRIBUTING.md), and [third-party provenance](NOTICE).

### Agent option reference

The discoverable [skill](skills/stitch-a1-video/SKILL.md) includes a maintained
[option reference](skills/stitch-a1-video/references/options.md) for all encode,
backend, motion, batch, GPS and verification flags. It also explains optional
workspace director/Resolve helpers; those helpers are not part of this public
package and are not required for CLI conversion.
