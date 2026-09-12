# Working on A1 Stitcher

This is the public software package, not the private footage/editing workspace.
Keep personal footage, vendor binaries, SDKs, metadata dumps, per-camera profiles,
paths, credentials, and generated media out of commits and releases. Tests should
create their own synthetic data. Only include third-party material with compatible
licensing and preserve attribution.

Use the public CLI and skill in `skills/stitch-a1-video/SKILL.md` for preparation.
When changing code, run Ruff, pytest (including FFmpeg integration tests), and a
wheel build. Exercise the installed wheel from outside the checkout before a
release. Technical checks and perceptual image quality are separate claims.

Preserve source files, existing outputs and profile boundaries. Maintain explicit
source-frame mapping, calibration fingerprints and receipts when modifying the
renderer. A tag or a 2:1 raster does not prove a calibrated, stabilized sphere.
