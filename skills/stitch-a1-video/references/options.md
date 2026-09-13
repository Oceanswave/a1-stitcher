# A1 CLI options and preparation handoff

The 0.8 CLI command line and JSON batch jobs share `Options` fields. Check installed
help/version before using this reference. No vendor runtime is required after
calibration; Metal needs macOS, a usable GPU and Swift command line tools.

## Stitch options

Required: `SOURCE`, `--calibration PATH`, `--first-frame N`, `--frames N`,
`--output PATH`. Paths in CLI calls use the current working directory; batch
paths resolve against the manifest directory. Outputs and receipts never overwrite.

| Option | Default | Effect |
| --- | --- | --- |
| `--width N` | `8192` | Full sphere width; height is N/2. Multiples of four, 64–8192. |
| `--lens-width N` | `0` | Zero selects native source resolution; explicit widths must be even, at least 32 and no larger than native. |
| `--encoding hevc10` | `hevc10` | MP4, libx265 CRF 12/medium, 10-bit 4:2:0; 16-bit decode/remap pipeline. |
| `--encoding prores` | — | MOV, prores_ks profile 3 (422 HQ), 10-bit 4:2:2; 16-bit pipeline. |
| `--encoding h264` | — | MP4, libx264 CRF 18/fast, 8-bit 4:2:0; 8-bit pipeline for smaller reviews. |
| `--backend auto` | `auto` | Preflight Metal on supported Macs, otherwise CPU; record selection/fallback. |
| `--backend cpu` | — | Portable CPU reference renderer. |
| `--backend metal` | — | Require the independent Metal renderer; fail if unavailable. |
| `--seam flow` | `flow` | Bidirectional correspondence checks and bounded local color balance. |
| `--seam multiband` | — | Experimental three-band overlap blend and bounded per-frame color changes; no temporal pixel averaging. |
| `--seam adaptive` | — | Experimental moving overlap path with temporal constraints. |
| `--seam feather` | — | Legacy angular feather for comparisons or unsuitable flow. |
| `--rolling-shutter auto` | `auto` | Use embedded readout duration and native sensor-row timing. |
| `--rolling-shutter-model trajectory` | — | Experimental: use 33 orientation samples across readout, transformed separately for each native lens. |
| `--rolling-shutter-model velocity` | `velocity` | Qualified average angular velocity; retained because trajectory results are mixed on real footage. |
| `--heading-reference-frame N` | `0` | Original frame defining fixed sphere yaw for every export from this source; `-1` uses the selected start. Must be covered by attitude/gyro and video. |
| `--rolling-shutter off` | — | Disable row correction for a controlled comparison. |
| `--occlusion-profile PATH` | absent | Camera/accessory-bound native visibility masks; alternate-lens replacement, fail on holes. See the profile section below. |
| `--gyro-profile PATH` | absent | Experimental anchored raw-gyro interpolation; requires a matching per-unit profile. |
| `--gyro-anchor-seconds N` | `0.1` | With a gyro profile, use recorded-attitude anchors spaced by 0.02–1 second; 0.02 retains all recorded anchors. |
| `--no-stabilization` | false | Hold global orientation at the first pose for diagnostics; row correction is a separate setting. |
| `--export-gpx` | false | Export the entire source GPS to `OUTPUT.gpx`, e.g. `sphere.mp4.gpx`. GPS must pass preflight. |
| `--threads N` | `4` | CPU/FFmpeg worker limit, 1–64. Does not control GPU core count. |
| `--timeout SECONDS` | `120` | Stalled frame/process bound, not a whole-job wall-time budget. |
| `--resume` | false | Verify/reuse only a matching completed video/receipt and requested GPX. |
| `--keep-work` | false | Retain temporary files and logs for diagnosis. |
| `--dry-run` | false | Preflight recipe, dependencies, profiles and selected range; do not render. |

Auto backend selection does not silently change image dimensions, codec or seam
mode. GPU kernels are independent Swift/Metal source shipped with the package.
The first process use compiles a temporary bridge. There is no downloaded binary
or vendor model. Low-resolution flow analysis stays on CPU; final sampling retains
original lens precision. CPU and GPU have small interpolation differences, so the
actual backend participates in receipt identity.

Measured with the 0.5 average-rate row model on an M1 Max with native 3840-pixel lenses and 16-bit flow processing:
Metal was 5.1×/13.8×/31.0× faster for the 2K/4K/8K stitching stage. A separate
three-frame full 8K ProRes job was 3.8× faster including startup and verification.
These are bounded measurements, not guarantees or a real-time claim.

Do not infer total rendering time from GPU kernel time. Measure compile/startup,
source decoding, CPU seam analysis, transfers, encoding and full verification.

### Practical commands

```sh
# Default full-quality interoperable MP4, plus the recorded flight track
a1-stitch stitch recording.insv --calibration calibration.json \
  --first-frame 300 --frames 180 --output sphere.mp4 --export-gpx

# Resolve finishing intermediate; retain the 8K/native defaults
a1-stitch stitch recording.insv --calibration calibration.json \
  --first-frame 300 --frames 180 --encoding prores --output sphere.mov

# Explicit lightweight preview; never use it as the finishing master
a1-stitch stitch recording.insv --calibration calibration.json \
  --first-frame 300 --frames 180 --width 2048 --lens-width 1440 \
  --encoding h264 --output preview.mp4
```

Use real, covered frame ranges; these indices are examples. An 8K sphere spreads
pixels around all 360 degrees; it is not an 8K rectilinear view. HEVC/ProRes do not
turn the tested SDR capture into log/HDR, and neither reconstructs occluded detail.

## Raw-gyro calibration

```sh
a1-stitch gyro-calibrate recording-a.insv \
  --validation-source recording-b.insv --output new-gyro-profile.json

a1-stitch stitch recording-b.insv --calibration calibration.json \
  --first-frame 300 --frames 180 --gyro-profile new-gyro-profile.json \
  --output gyro-comparison.mp4
```

Use two different recordings from the same embedded lens configuration. Calibration
needs sufficiently varied motion on all axes and at least 55 seconds of overlapping
data. It fits a proper rotation (no scale/shear), bounded bias and timing using
2 Hz low-pass data; held-out blocks and transfer residuals are stored. Gaps,
saturation, missing layouts, unsupported rates and failed fits are rejected.

The gyro profile is separate from lens/mount calibration. Never overwrite or
confuse the two. The query offset aligns raw gyro to the recorded attitude clock;
the lens profile's video/attitude shift still applies. Anchored integration matches
both recorded endpoints and limits accumulated drift to one attitude interval.
The optional mode defaults to 0.1-second anchors. `--gyro-anchor-seconds 0.02`
uses every recorded anchor for comparison; wider spacing up to one second reduces
anchor-imposed jitter but allows longer inter-anchor drift. Raw high-frequency
motion is still experimental. Synthetic vibration recovery
and low-pass transfer scores cannot prove real image timing or cinematic motion.
Keep recorded attitude as the default until matched moving imagery supports a change.

## GPS, inspection and verification

- `inspect SOURCE [--output PATH] [--redact-path]`: bounded metadata inventory;
  includes observed record-4 exposure duration/timing statistics, without applying
  them to the fitted frame clock. Path redaction is not location anonymization of separately exported GPS.
- `gpx SOURCE --output PATH [--gap-seconds 10] [--dry-run] [--resume]`: GPX 1.1
  with UTC, latitude/longitude, reported elevation, and optional speed/course
  extensions. Missing/void GPS does not yield an invented route.
- `verify VIDEO [--receipt PATH] [--quick] [--timeout 600]`: full decode by default;
  `--quick` checks metadata/checksum without claiming decode coverage.
- `compare CANDIDATE --reference STUDIO --reference-first-frame OFFSET
  --samples 0,15,30 --output-dir NEW_DIR [--width 2048]`: sample indices are local
  candidate frames; OFFSET maps candidate zero to the reference. Analysis width
  is 512–4096, independent of delivered sphere resolution. Both videos must have
  the same frame rate and full-sphere projection. Per-frame alignment hides some
  motion, so also review an unaligned or single-rotation moving comparison.
- `calibrate`: required source/reference/first-source-frame/holdouts/output,
  optional `--samples`, `--evidence-dir` and `--frame-clock nominal|exposure`; read the main skill for conventions.
- `migrate-calibration INPUT --output NEW_PROFILE`: explicit initial-prototype
  schema migration; retained evidence does not gain new quality qualification.
- `doctor`, `--version`, and each command's `--help` report installed capabilities.

## JSON batches

```json
{
  "schema_version": 1,
  "jobs": [{
    "source": "recording.insv",
    "calibration": "calibration.json",
    "output": "prepared/sphere.mp4",
    "first_frame": 300,
    "frames": 180,
    "width": 8192,
    "lens_width": 0,
    "encoding": "hevc10",
    "backend": "auto",
    "seam": "flow",
    "rolling_shutter": "auto",
    "rolling_shutter_model": "velocity",
    "heading_reference_frame": 0,
    "export_gpx": true
  }]
}
```

`a1-stitch batch jobs.json --dry-run` preflights every job;
`a1-stitch batch jobs.json --resume` processes sequentially and verifies completed
outputs. Optional stitch fields include `occlusion_profile`, `gyro_profile`, `gyro_anchor_seconds`, `threads`, `timeout`,
`no_stabilization`, `keep_work` and `resume`. CLI spelling changes hyphens to
underscores in JSON. Each source/calibration/output/gyro-profile/occlusion-profile path is relative
to the manifest directory unless absolute. Do not add unknown metadata fields to
jobs; put editorial associations in a separate handoff document.

## Director/Resolve integration, when available

These are **workspace helpers**, not commands installed by the public A1 package.
Use them only in a workspace containing `scripts/director.py` and its configured
library/history. Preserve existing editorial rules and projects.

```sh
python3 scripts/director.py index
python3 scripts/director.py search mud --minimum 4 --exclude-used
python3 scripts/director.py prepare-a1 SELECT_ID \
  --calibration calibration.json --backend metal
# Execute the returned render_argv / batch manifest.
python3 scripts/director.py register-a1 sphere.mp4.receipt.json
# After actually reviewing the entire prepared range:
python3 scripts/director.py register-a1 sphere.mp4.receipt.json \
  --motion-review motion-review.json
python3 scripts/director.py index
python3 scripts/director.py resolve-handoff SELECT_ID --output resolve-selects.json
```

`prepare-a1` coalesces overlapping original ranges with handles and emits a
preflighted full-quality batch and select associations. `--a1-cli PATH` selects
a checked executable. `register-a1` verifies the video and GPX before registering
it as `needs_motion_review`. A review document must bind the output SHA-256,
cover `[0, FRAME_COUNT]`, name `reviewed_by`, contain actual `notes`, and list
existing `evidence_paths`; `checks` must explicitly pass `motion`, `seams`,
`horizon` and `subject_geometry`. Do not manufacture that document from test status.

Search/Resolve handoff carries event history and distinguishes known used events,
unknown mapping and required event review. `--exclude-used` only excludes known
used events; it does not certify the remaining shots as fresh. Original-frame
bindings connect new exports/crops to prior events. A ready handoff preserves
full-resolution paths, trim ranges, color, receipts and any flight-track sidecar;
it neither assembles a film nor grants publication approval.

## Exposure and visibility profiles

`calibrate --frame-clock exposure` refits mount/time alignment against a
source-matched Studio sphere using frame-indexed exposure midpoints. All other
calibration requirements remain: an exact first-source-frame mapping, varied
training observations, disjoint holdouts and a new output file. Default
`--frame-clock nominal` retains schema 1. The exposure result uses schema 2 and
requires CLI 0.7 or newer. Never edit the schema/clock label of an old fitted
profile; the constant offset would then describe the wrong clock.

The profile determines the stitch clock automatically. Exposure timestamps minus
half shutter duration feed attitude, heading and row queries; no output frames
are shifted or interpolated. Missing frame-zero anchors, gaps, unsupported drift,
overlong exposure and missing selected-frame coverage fail preflight. These
checks do not prove image timing. Compare matched motion and holdouts: the first
0.7 trials improved short motion diagnostics but worsened aggregate reference
holdouts, so nominal remains the default.

For a visible camera/guard region:

```sh
a1-stitch mask-template recording.insv --output visibility.json
# Fill the new template with measured native-image exclusions before previewing.
a1-stitch mask-preview recording.insv --occlusion-profile visibility.json \
  --frame 300 --output-dir visibility-review

a1-stitch stitch recording.insv --calibration calibration.json \
  --occlusion-profile visibility.json --first-frame 300 --frames 180 \
  --output masked-sphere.mp4
```

The template contains `schema_version: 1`, `kind: a1-native-visibility-v1`, the
camera's `lens_fingerprint`, recorded `propeller_guard_status`, `feather_pixels`
and two `lenses` entries. Preserve the generated identity/configuration fields.
A source with unknown guard state cannot create or use a profile; do not guess it.
Each lens entry supports:

- `exclude_polygons`: up to 64 polygons of 3–128 x/y vertices each, normalized
  from 0 to 1 over the **native square lens image**, origin at top left. Mark the
  obstruction, including its observed motion/blur envelope. Lens 0 and lens 1
  use separate coordinate systems; this is not a panorama mask.
- `max_angle_degrees`: optional optical-axis half-angle, 85–110°, or `null`.
  A broad angle cutoff can discard good overlap, expose flare or leave holes;
  prefer a measured local outline where that preserves more real scene detail.
- Shared `feather_pixels`: 1–16, default 3, measured on the fixed **512×512 mask**
  grid. It softens the allowed side of an exclusion without making excluded
  pixels visible again. It is not a count of 8K output pixels.

At least one angle limit or polygon must be supplied. `mask-preview` writes
source/overlay PNG pairs and a frame/profile report to a new directory; red
marks exclusions. It samples at up to 1024 pixels per lens and does not render
or qualify a finished sphere. Check several frames, including sharp turns and
longer exposures. Native masks follow lens projection and rolling-shutter
correction on both backends, and masked pixels are excluded from seam analysis.

The final blend replaces exclusions using actual pixels from the other lens,
including fallback outside the usual seam preference. If neither lens covers a
pixel, rendering fails rather than publishing a hole or hallucinated fill.
A profile can still produce parallax, flare or a visible seam. This is authored
visibility exclusion, not automatic rotating-blade detection, learned inpainting,
shadow removal or a complete Studio equivalent. Keep it opt-in and review the
whole intended interval before accepting a production master.

## Image timing, masks and continuous comparisons

| Command | Required arguments | Optional settings / limits |
| --- | --- | --- |
| `sync-calibrate SOURCE` | `--calibration BASE --gyro-profile GYRO --first-frame N --frames N --output NEW --evidence-dir NEW_DIR` | `--step 3` (1–10); `--gyro-anchor-seconds 0.1` (0.02–1); 60–1800 frames. Base schema 1 or 2 only. |
| `mask-propose SOURCE` | `--calibration PROFILE --first-frame N --frames N --output NEW --evidence-dir NEW_DIR` | `--samples 24` (12–60); 60–1800 frames; native analysis at 512 pixels. |
| `mask-approve PROPOSAL` | `--output NEW --review-notes TEXT` | 8–4000 characters documenting actual review; nonempty schema-2 proposal only. |
| `benchmark CANDIDATE` | `--reference SPHERE --reference-first-frame N --frames N --output-dir NEW_DIR` | `--width 1024` (512–2048, multiple of four); 2–1800 frames; identical known CFR; six 256-pixel fixed 90° views. |

All outputs are new paths. The benchmark offset maps candidate frame zero into
the reference; it is not the original's absolute source frame. The two frame
mappings must be reconciled explicitly. Native-lens downsampling and small review
spheres do not establish native-resolution quality. Benchmark angular acceleration
is in degrees per frame squared, not degrees per second squared. Scene motion,
translation/parallax and changing light affect its metrics; unmeasured pairs are
reported and never interpolated. No per-frame alignment hides candidate motion.

Timing uses 768-pixel native feature tracks, bidirectional checks, robust background
rotation filtering and four contiguous temporal blocks. The search spans ±40 ms
and 0.5–1.5× native readout. A qualifying fit must improve held-out median angular
error by at least 1%, keep its p95 within 1% of baseline, avoid search boundaries
and pass a scaled Jacobian observability check. These gates are interval checks,
not an independent-camera or separate-recording qualification.

A rejected timing analysis returns exit 0 with JSON `status: rejected` and writes
only evidence. Check status before attempting a render. A schema-3 calibration
records readout scale, base-profile fingerprint, gyro fingerprint and anchor
spacing. Rendering requires that gyro profile/spacing, `--rolling-shutter auto`
and `--rolling-shutter-model trajectory`; incompatible combinations fail preflight.
The base nominal/exposure clock remains explicit. Older CLIs reject schema 3.

A proposal is not a verified aircraft mask. Inspect both native lenses over the
range, trim scene/rim false positives, and record coverage in `mask-approve` notes.
The proposal includes sampled frames and source/calibration identity. Approved
schema-2 visibility profiles add a temporally damped contrast check and immediate
clipping rejection for forced alternate-lens replacement. Low-texture sky can
therefore make replacement unavailable. This is deliberate abstention, not an
invitation to loosen an exclusion until the job passes. Legacy authored schema-1
masks keep their earlier behavior. `mask-preview` can inspect empty templates and
unapproved proposals without allowing them to render.

Multiband uses the existing calibrated, confidence-checked overlap. It adds two
bounded low-frequency difference terms with 2.4°/4.8° transitions while native
high-frequency detail keeps the 1.2° transition. The analysis belt remains ±8°;
unsupported/clipped/masked regions do not receive a correction. Per-frame log-gain
updates are limited to 0.01 in this mode. Default `flow` behavior is retained.
