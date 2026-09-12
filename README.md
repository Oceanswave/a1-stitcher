# A1 Stitcher

Independent **Antigravity A1 → equirectangular MP4** conversion, with recorded-attitude
stabilization and a command line designed for batch work and agents.

A1 Stitcher reads the two original HEVC lens tracks, their embedded calibration,
and the timestamped attitude record. It renders a complete 360° sphere, adds
standard spatial metadata, and verifies the finished video. Once a camera has
been calibrated, conversion does not require Antigravity Studio.

**Status: alpha, with a new image-quality pipeline in 0.2.0.** Conversion now
corrects native sensor-row timing, aligns lens overlap using checked optical
flow, and reduces local lens color differences. Recorded tests show cleaner
seam detail and substantially lower geometric error during a rapid turn;
see [measurements and limits](docs/quality-v0.2.md).
Camera/propeller removal, severe occlusion, high-frequency vibration and broader
camera coverage remain open. This is an independent implementation, not an
official Antigravity or Insta360 product or a reproduction of proprietary
FlowState/AI stitching.

## Install

Python 3.12+, macOS or Linux, and FFmpeg/ffprobe with HEVC decoding and libx264
encoding are required. Install FFmpeg separately using your normal package manager.

```sh
# From a checkout
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/a1-stitch doctor

# Or install the tagged GitHub source as an isolated CLI with uv
uv tool install 'git+https://github.com/Oceanswave/a1-stitcher.git@v0.2.0'
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
  --width 2048 --lens-width 1440 \
  --output selected-sphere.mp4
```

Frames use the original's frame rate; `--frames` is a count, not an inclusive end.
The default is a 2K review sphere. Use `--width 4096 --lens-width 3840` to retain
more source detail, subject to the current CPU cost. The renderer supports up to
8192 pixels wide using strips to bound intermediate memory. Support for a
resolution is not a claim of qualified 8K finishing quality.

The output is 8-bit limited-range SDR BT.709 H.264, with monoscopic Spherical
Video V2 metadata and fast-start MP4 layout. The tested originals are full-range
SDR BT.709. Unknown/log/HDR/higher-bit-depth inputs are rejected rather than
silently flattened. No LUT is applied. A1 audio is not supported; inputs with an
audio track are refused instead of dropping it.

The default `--seam flow` uses bidirectional overlap correspondence, rejects
unreliable/oversized displacement, and matches local color without brightening
the cleaner lens. It samples the original lenses directly at the output's
resolution. `--rolling-shutter auto` uses the embedded readout duration and
recorded angular motion to correct each native sensor row. Missing readout
metadata disables that correction; invalid values fail preflight. For controlled
comparisons or difficult footage, `--seam feather --rolling-shutter off` retains
the original geometric/blending path. Both choices participate in cache identity.
These corrections cost additional CPU time and cannot recover occluded detail
or remove motion blur. Review the intended shot in motion.

A matching `.mp4.receipt.json` records source range, camera profile, processing
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
      "width": 2048,
      "lens_width": 1440,
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
