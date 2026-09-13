# A1 Stitcher

Independent **Antigravity A1 → equirectangular MP4** conversion, with recorded-attitude
stabilization and a command line designed for batch work and agents.

A1 Stitcher reads the two original HEVC lens tracks, their embedded calibration,
and the timestamped attitude record. It renders a complete 360° sphere, adds
standard spatial metadata, and verifies the finished video. Once a camera has
been calibrated, conversion does not require Antigravity Studio.

**Status: alpha, with opt-in exposure synchronization and aircraft visibility masks in 0.7.0.**
Defaults now produce an 8192×4096 sphere from native lens frames, with 16-bit
image processing and 10-bit HEVC encoding. ProRes 422 HQ is available for finishing.
An independent Metal renderer accelerates supported Macs; the CPU reference
remains portable. The converter corrects native sensor-row timing, aligns lens
overlap with checked optical flow, and confines lens color matching to measured
areas. An optional row model samples orientation through each scan, and a fixed source-frame
heading keeps adjacent exports consistent. See [the 0.6 motion report](docs/quality-v0.6.md)
and [Metal performance measurements](docs/quality-v0.5.md).

Experimental raw-gyro interpolation is available with a per-unit calibration and
separate-recording transfer validation. Recorded attitude remains the default:
a higher sensor sample rate alone does not qualify high-frequency image correction.
Exposure-aware calibration and camera-bound visibility masks are now available.
Masks replace excluded housing/propeller pixels only where the other lens sees
the scene; automatic blade detection and reconstruction remain open.
See [the 0.7 evidence and limits](docs/quality-v0.7.md). Severe occlusion and
broader camera coverage remain open.
This is an independent implementation, not an official Antigravity or Insta360
product or a reproduction of proprietary FlowState/AI stitching.

## What conversion preserves and bakes in

**Keep the INSV originals. The exported MP4 is a rendered 360° working copy,
not a replacement for the camera recording.** Conversion never modifies the
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
| Re-stitching and lens geometry | One full equirectangular sphere, rendered from both calibrated lens tracks. | Dewarp, lens registration, seam decisions, flow and local color matching are baked into pixels. Separate fisheye images and overlap cannot be recovered from the composite. | **High** — keep INSV to improve stitching, change calibration, handle parallax differently or use a future vendor algorithm. |
| Stabilization and rolling shutter | Recorded-attitude stabilization with native-row correction; optional varying row trajectories and calibrated raw-gyro interpolation. A fixed source-frame heading is shared across exports. Further global rotation and image-based correction remain possible. | Applied corrections are baked in. Raw IMU, original attitude samples and sensor-row measurements are not embedded in the generated video. The gyro profile in the receipt describes processing; it is not the raw sensor stream. | **High** — re-running sensor-based stabilization or changing row timing requires the original. The exported sphere can still be reframed freely. |
| View, framing and depth | Complete 360° × 180° monoscopic coverage, with later yaw/pitch/roll, field of view, tracking and animated reframes. | No stereo depth or change of the physical viewpoint is created. This is a capture limit, not something equirectangular export discards. | **Low** for ordinary reframing — the full sphere is retained. An overhead drone cannot become a ground-level camera through reframing. |
| Spatial detail and compression | Default 8192×4096 output from native-size lenses; optional ProRes 422 HQ or smaller review encodes. | Projection interpolation, seam blending and another lossy encode change pixels. Native-resolution processing avoids the former 1440-pixel lens downsample; an 8K sphere does not imply 8K detail in a narrow reframe. | **Medium** at the new defaults; **High if a small preview is used for finishing**. Render a fresh master from INSV when changing quality settings. |
| Color precision and chroma | Default 16-bit image processing → 10-bit 4:2:0 HEVC, CRF 12. ProRes 422 HQ offers 10-bit 4:2:2; H.264 review mode uses 8-bit 4:2:0. | The tested original is 8-bit 4:2:0 SDR. Extra processing precision reduces new rounding but does not create captured dynamic range or missing color detail. HEVC and ProRes are still lossy generations. | **Medium** for grading — use HEVC10 or ProRes and avoid repeated intermediate re-encodes. This fixes the old always-8-bit output limitation, not the source's capture limits. |
| Color space, range and log/HDR | Tagged limited-range SDR BT.709 suitable for SDR Resolve/Fusion grading. No LUT is applied. | Tested sources are full-range SDR BT.709. The range conversion changes signal encoding, not intended display contrast when interpreted correctly. Log/HDR/higher-bit-depth inputs remain rejected. | **Low** for correctly interpreted supported SDR; **High if log/HDR ingest is required** — it is unsupported, not silently flattened. |
| Exposure telemetry and synchronization | `inspect` reports shutter/timestamp statistics. Optional schema-2 calibration fits an exposure-midpoint attitude clock; the receipt records it. | Raw exposure samples are not copied into MP4. The chosen timing is baked into stabilization, while output frame cadence stays unchanged. Two short moving tests were promising but reference holdouts were mixed. | **High** for future sensor reprocessing; **Low** for routine cutting. Keep INSV and refit with `calibrate --frame-clock exposure`; never append a guessed offset to an old profile. |
| Camera/propeller visibility | Optional camera/accessory-bound native masks select visible pixels from the other real lens; the profile is stored in the receipt. | Lens selection is baked into the composite. This is authored exclusion, not automatic blade detection or reconstruction of doubly occluded detail. Broad masks can worsen flare or seams; uncovered pixels cause a failed job. | **High when the aircraft intrudes**; **Low when the default seam already avoids it**. Keep originals to revise the profile and inspect moving boundaries. |
| Frame timing and selected duration | Selected consecutive frames at the original constant frame rate, with exact first-source-frame/count in the receipt. | Unselected frames are absent from this working copy. No retiming or frame interpolation is added by stitching. | **Medium** — include handles; the archive is needed for longer trims or a different event. |
| Audio | Typical tested A1 inputs have no audio track. | Inputs containing audio are refused; this release has no audio-preserving conversion path. | **High if the input contains sound** — conversion is blocked rather than silently dropping it. Keep any separate sound recordings for the editor. |
| GPS flight profile | Optional GPX sidecar with recorded position, UTC, reported elevation and speed/course extensions; checksum in the video receipt. Standalone extraction is also available. | GPS is not embedded as the original telemetry track. GPX covers the entire source recording, even for a short video selection. Exact UTC/video alignment and altitude datum remain unqualified; missing/invalid GPS causes the requested export to fail. | **Medium** for editorial maps; **High for precise flight/sensor analysis**. Keep originals and the sidecar; do not treat reported elevation as verified AGL or infer a complete multi-file flight. |
| Other camera data and Studio controls | Standard sphere/stereo tags plus a receipt containing source identity, frame mapping, profiles, versions, backend and output checksum. | Other telemetry/subtitle tracks, the vendor trailer, raw sensor records and proprietary project/edit controls are not copied. This does not reproduce FlowState/AI stitching, automatic aircraft removal or all Studio behaviors. | **High** for future camera-specific reprocessing; **Medium** for everyday editing. Neither receipt nor GPX is a complete metadata archive. |
| Container and editor interoperability | Standard MP4 (HEVC/H.264) or MOV (ProRes), fast-start layout and Spherical Video V2 metadata. | INSV was already an MP4-family container, but with separate lens tracks and proprietary data. Conversion adds a usable sphere; renaming/remuxing alone cannot. A 360-aware editor is still needed for reframing. | **Low** loss and a substantial interoperability gain. The original and the generated sphere serve different purposes. |
| CPU versus Metal | The same calibrated projection, seam and row-correction models; chosen backend is recorded. | Small numeric/interpolation differences remain between implementations. GPU speed does not add source detail, restore blur or alter which metadata is preserved. | **Low** on qualified comparisons — choose automatic Metal for speed or CPU for the reference path; neither removes the need for motion review. |

Archive the untouched INSV files, lens calibration and any gyro profile alongside
output receipts. Keep GPX when exported and preserve source-frame mappings for
reference media. The generated MP4/MOV and sidecars are working derivatives,
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

# Or install the tagged GitHub source as an isolated CLI with uv
uv tool install 'git+https://github.com/Oceanswave/a1-stitcher.git@v0.7.0'
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

### Calibrate a camera once

Supply an existing **full 2:1 stitched equirectangular reference** from the same
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
  --calibration camera-calibration.json \
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
Source cache identity uses file stat plus first/last MiB hashes; it is not a full
cryptographic hash of the original recording. Changed source stat, edge content,
calibration, media settings, package version or FFmpeg version invalidates reuse.

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
