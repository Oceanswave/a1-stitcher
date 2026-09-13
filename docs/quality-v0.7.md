# 0.7 exposure synchronization and aircraft visibility

This pass adds independently implemented exposure-aware attitude queries and
native lens visibility profiles. Both are optional. The nominal calibration,
fixed flow seam and average-rate sensor-row model remain the defaults.

## What Studio inspection established

Read-only inspection of a locally installed Studio 2.0.4 found separate exposure
lookup/frame-index conversion paths, a timing conversion using half shutter
duration, fisheye visibility-mask controls and propeller-guard configuration.
The metadata field-number constant identifies protobuf field 175 as the guard
status; the observed enum distinguishes no guard and three accessory states.
Both tested recordings report zero. These are format/interface observations,
not proof of the complete vendor removal algorithm. Occlusion-related tracking
symbols do not establish an aircraft-inpainting model.

The official [editing guide](https://www.antigravity.tech/sa/blog/Drone-Photography-Videography/drone-360-video-editing-guide)
also describes propeller-guard and stitching controls. The
[A1 manual](https://static.antigravity.tech/assets/3355c03564f5547cb2e0e3fd03ed6855/Antigravity_A1_User_Manual_EN_V1.0.pdf)
connects installed guards with stitching calibration. No vendor code, masks,
models, disassembly, internal parameter tables or private camera profile is
included in this repository or needed by the renderer.

## Exposure-aware clock

In each of two inspected recordings, exposure record index 8 exactly matches the
first video timestamp. Subsequent timestamps follow the original constant-rate
frame indices. Maximum positive deviations from nominal timing were 0.569 ms
and 0.674 ms; this is small timestamp variation, not long-term clock drift.

`calibrate --frame-clock exposure` fits mounting and offset against the midpoint
clock `exposure_timestamp - shutter_duration / 2`. Schema 2 explicitly binds
that clock to the new calibration. It cannot be used by older CLI versions or
silently migrated back to nominal timing. A normal schema-1 calibration remains
nominal. Editing a JSON schema marker is not a calibration procedure.

The exposure track must contain a unique exact frame-zero timestamp. Every
subsequent ordinal must agree with frame cadence to within one tenth of a frame;
missing records, unsupported drift, overlong shutters and uncovered queries
fail. The same clock drives center pose, heading reference and native-row motion
queries. This is attitude synchronization; it does not retime the two video
tracks, recover blur, grade exposure or prove separate timing for each sensor.

### Reference fit and moving evidence

A refit using seven previously matched training observations and three held-out
observations changed the fitted offset from 13.809 ms to 14.150 ms. Training RMS
was essentially unchanged (0.12255° to 0.12268°); holdout RMS worsened from 0.317°
to 0.366°. Exposure-aware fitting is therefore not universally better on this data.

Four matched 90-frame sequences were rendered at 4096×2048 from native 3840-pixel
lenses, using Metal, ProRes 422 HQ, fixed flow, average-rate row correction and
the same calibrated gyro with 0.1-second attitude anchors. Only the lens/mount
calibration and its associated frame clock differ within each pair. Each output
passed full decode, frame-count and spatial/color metadata verification.

A fixed 90° reframe was aligned once at frame zero, without subsequent image
stabilization. Background affine acceleration was measured at 960×540 over all
90 frames. It includes translation, parallax and tracking noise. Lower values
are favorable for this diagnostic but do not establish perceptual acceptance.

| Sample / clock | Median acceleration, pixels | 95th percentile, pixels |
| --- | ---: | ---: |
| A / nominal | 0.557 | 3.150 |
| A / exposure midpoint | 0.532 | 3.136 |
| B / nominal | 0.474 | 2.516 |
| B / exposure midpoint | 0.433 | 1.724 |

The second sample's 95th percentile fell about 31.5%; the first changed by less
than 1%. These two three-second clips and mixed reference residuals do not
justify changing the default clock. They also do not qualify high-frequency
IMU timing across other cameras, firmware or exposure modes. See the
[0.6 report](quality-v0.6.md) for the separately measured row-trajectory results.

## Camera and propeller visibility masks

`mask-template` creates a camera/accessory-bound profile. Fill it with observed
native-image exclusion polygons or maximum lens angles, then inspect it with
`mask-preview`. `stitch --occlusion-profile` samples these masks after lens
projection and native-row correction, so the exclusions move with the camera
rather than remaining fixed in the output panorama.

Excluded pixels do not participate in overlap correspondence/color estimation.
The final blend reduces their weight and uses the other real lens where it is
valid. If the usual preferred lens is fully excluded, the renderer can select
the alternate valid lens. If neither lens supplies a panorama pixel, the job
fails rather than publishing black holes or fabricated scene detail. CPU and
Metal implement the same behavior with bounded 512×512 soft masks.

Synthetic images verify exact replacement with pixels from the alternate lens,
accessory/camera mismatch rejection, no-overwrite behavior and uncovered-region
failure. Native housing outlines were also inspected on two private recordings.
A broad circular mask changed an already clean flow seam unfavorably in strong
sun flare. A narrower housing polygon reduced visible housing contamination in
legacy feather blending while retaining more useful overlap. The current fixed
flow seam already avoids most housing in these samples; a large improvement to
the default output is not established.

A separate 90-frame masked-flow export passed full decode and reported zero
uncovered pixels. Its background-motion diagnostic was 0.518 median / 2.673
95th-percentile pixels versus 0.474 / 2.516 without the mask. Masking is not a
stabilization improvement; changes to overlap analysis and feature tracking can
affect that diagnostic. No whole-sphere motion acceptance is claimed.

These are authored visibility masks, not an automatic aircraft detector or
learned propeller remover. Rotating blades, blur, shadows and reflections can
extend beyond an authored outline. The alternate lens can have flare or nearby
parallax. Neither lens can reveal a scene surface that both occlude. Inspect
moving seams before accepting a profile; coverage tests and sampled stills are
not whole-range motion acceptance.

## Reproduction and coverage

The public tests generate their own camera, exposure and obstruction data.
Hardware parity covers 8/16-bit images, all three seam modes, average-rate and
trajectory row models, readout on/off, and masks on/off. FFmpeg tests exercise
exposure-bound calibration, receipts, reuse and native visibility previews.
Private originals and camera profiles are retained outside this repository.
Commands, profile limits and review steps are documented in the
[skill options reference](../skills/stitch-a1-video/references/options.md).

Local validation passed 300 tests, including 49 actual Metal cases and FFmpeg
integration, plus Ruff and a wheel build. An isolated installed wheel, run from
outside the checkout, produced a three-frame 8192×4096 HEVC10 export from native
lenses with exposure timing, visibility masks, gyro-fed row trajectories and a
GPX sidecar enabled together. Full decode, spatial/color metadata and checksums
passed. This is a packaging/integration check, not additional perceptual evidence.
