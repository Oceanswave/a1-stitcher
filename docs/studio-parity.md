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
| Exposure / gyro synchronization | Timing conversion accounts for exposure duration separately from offsets. | 0.7 adds refitted exposure-midpoint calibration with checked frame correspondence; nominal profiles retain their clock. | **High:** two short moving tests improve, but reference holdouts are mixed; it remains opt-in. |
| Raw gyro processing cost | Studio has filtered gyro/orientation paths; their performance is not inferred from names. | Contiguous interpolation data and reused anchor corrections reduce repeated work in the independent integrator. | **Medium:** decode, optical flow and encoding remain outside this optimization. |
| Lens image fusion | Separate optical-flow and image-fusion controls; multiscale-related symbols. | Confidence-gated overlap flow and local exposure/color ratios. | **Medium:** multiscale fusion is not implemented; it needs moving-seam qualification. |
| Propellers / camera / guards | Guard metadata field 175 and fisheye visibility-mask controls; exact automatic removal behavior not established. | 0.7 adds native visibility profiles and alternate-lens replacement on CPU/Metal, with preview overlays. | **High** where the aircraft is visible; both-lens occlusion fails; blade detection, flare and parallax remain open. |
| Exposure blur and occlusion | No qualified independent equivalent from this pass. | Preserves captured blur; cannot recover unseen surfaces. | **High** for difficult scenes. Row correction changes geometry, not exposure sharpness. |
| Reframing / tracking / creative transitions | Editor controls are distinct from preparing the sphere. | Full sphere remains available to a 360-aware editor or a separate camera-path tool. | **Medium:** CLI does not yet author a tracked virtual-camera path or complete film. |
| Color / HDR / log / audio modes | Broad resources exist in Studio, not proof of A1 support for each mode. | Explicitly tested SDR ingest, 16-bit processing, 10-bit HEVC/ProRes; unsupported inputs rejected. | **High** when an unsupported capture mode is required. |

Exposure synchronization and visibility profiles now have independent implementations.
Both remain opt-in: use the [0.7 evidence](quality-v0.7.md) to separate measured
improvements from unresolved sensor timing and occlusion. No additional timing
correction is applied to an existing nominal profile. See also
[the archive/export differences](../README.md#what-conversion-preserves-and-bakes-in).
