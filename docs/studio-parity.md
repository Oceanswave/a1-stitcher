# Studio functionality and independent equivalents

This pass examined a locally installed Antigravity Studio 2.0.4 application,
using read-only interface metadata, exported symbol names and targeted timing
inspection. Those observations identify likely processing stages; a symbol name
alone does not establish that a stage runs for every A1 mode. No vendor binary,
model, disassembly or copied implementation is distributed in this package.

| Function | Studio observation | Independent CLI status | Remaining importance |
| --- | --- | --- | --- |
| Native lens geometry and stitching | Calibrated two-lens projection and overlap processing. | Embedded geometry, per-unit mount calibration, checked flow, bounded color balance; CPU and Metal. | **High:** close parallax and occlusion remain difficult. |
| Within-frame motion | Separate rolling-shutter and orientation/flow-map paths. | 0.6 optionally samples the chosen orientation trajectory through each native sensor scan. Mixed real-footage results retain average-rate correction as the default. | **High:** sensor-to-image timing still limits real vibration correction. |
| Stable orientation / direction lock | Direction-lock controls and spline-smoothing symbols are present. | Recorded attitude or calibrated anchored gyro; 0.6 adds one explicit source-frame heading reference across exports. | **Medium:** this is fixed yaw, not Studio's undocumented direction-lock/spline implementation or automatic subject tracking. |
| Exposure / gyro synchronization | Timing conversion accounts for exposure duration separately from offsets. | 0.7 adds exposure-midpoint clocks; 0.8 jointly fits image/gyro offset and row readout with temporal holdouts and explicit dependency checks. | **High:** fits can be rejected; local holdouts do not establish transfer or Studio-equivalent stabilization. |
| Raw gyro processing cost | Studio has filtered gyro/orientation paths; their performance is not inferred from names. | Contiguous interpolation data and reused anchor corrections reduce repeated work in the independent integrator. | **Medium:** decode, optical flow and encoding remain outside this optimization. |
| Lens image fusion | Separate optical-flow and image-fusion controls; multiscale-related symbols. | Confidence-gated flow and local ratios, plus opt-in three-band overlap blending and limited gain changes in 0.8. | **Medium:** broader fusion, temporal seams and flare handling still need qualification; the implementation is independent. |
| Propellers / camera / guards | Guard metadata field 175 and fisheye visibility-mask controls; exact automatic removal behavior not established. | Native visibility on CPU/Metal; 0.8 proposes fixed obstructions from multiple frames and checks clipping/contrast for forced alternate-lens replacement after review. | **High** where the aircraft is visible; both-lens occlusion fails; blade detection, flare and parallax remain open. |
| Exposure blur and occlusion | No qualified independent equivalent from this pass. | Preserves captured blur; cannot recover unseen surfaces. | **High** for difficult scenes. Row correction changes geometry, not exposure sharpness. |
| Reframing / tracking / creative transitions | Editor controls are distinct from preparing the sphere. | Full sphere remains available to a 360-aware editor or a separate camera-path tool. | **Medium:** CLI does not yet author a tracked virtual-camera path or complete film. |
| Color / HDR / log / audio modes | Broad resources exist in Studio, not proof of A1 support for each mode. | Explicitly tested SDR ingest, 16-bit processing, 10-bit HEVC/ProRes; unsupported inputs rejected. | **High** when an unsupported capture mode is required. |

Exposure synchronization and visibility profiles now have independent implementations.
These remain opt-in: use the [0.8 evidence](quality-v0.8.md) to separate measured
improvements from unresolved sensor timing and occlusion. No additional timing
correction is applied to an existing nominal profile. See also
[the archive/export differences](../README.md#what-conversion-preserves-and-bakes-in).
