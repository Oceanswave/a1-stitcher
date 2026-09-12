# A1 CLI options and preparation handoff

The 0.5 CLI command line and JSON batch jobs share `Options` fields. Check installed
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
| `--seam adaptive` | — | Experimental moving overlap path with temporal constraints. |
| `--seam feather` | — | Legacy angular feather for comparisons or unsuitable flow. |
| `--rolling-shutter auto` | `auto` | Use embedded readout duration and native sensor-row timing. |
| `--rolling-shutter off` | — | Disable row correction for a controlled comparison. |
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

Measured on an M1 Max with native 3840-pixel lenses and 16-bit flow processing:
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
  path redaction is not location anonymization of separately exported GPS.
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
  optional `--samples` and `--evidence-dir`; read the main skill for conventions.
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
    "export_gpx": true
  }]
}
```

`a1-stitch batch jobs.json --dry-run` preflights every job;
`a1-stitch batch jobs.json --resume` processes sequentially and verifies completed
outputs. Optional stitch fields include `gyro_profile`, `gyro_anchor_seconds`, `threads`, `timeout`,
`no_stabilization`, `keep_work` and `resume`. CLI spelling changes hyphens to
underscores in JSON. Each source/calibration/output/gyro-profile path is relative
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
