# Antigravity A1 recording modes

Scope: **Antigravity A1 only**. Checked against official specifications and update
notes on 2026-09-13. Camera capabilities, accepted input structure and demonstrated
image quality are different levels of coverage.

| Capture option | Documented A1 capability | CLI coverage and remaining work |
| --- | --- | --- |
| Standard 8K video | 7680×3840 at 30/25/24 fps | Two square lens tracks, H.264/H.265 and matching constant frame rates fit the input contract. Real qualification uses HEVC, 3840×3840 per lens, 30000/1001 fps, full-range 8-bit BT.709. Other rates/codecs need real captures and motion review. |
| Standard 5.2K video | 5248×2624 at 60/50/30/25/24 fps | Resolution/rate/codec combinations have synthetic input-contract tests. Native geometry, timing and output quality need real samples. |
| Standard 4K high-frame-rate video | 3840×1920 at 100 fps | Within the normal input contract; synthetic profile checks cover 100 fps. Needs a real original to validate pose cadence, sensor timing and fast motion. |
| 4K slow motion | 3840×1920 at 30/25/24 fps playback | **Not supported yet.** Capture and playback time need an explicit mapping for stabilization, pilot follow and trimmed sound. Playback fps alone cannot supply it. |
| Timelapse | Added in the May 2026 spring update | **Not supported yet.** Needs interval timestamps and a validated mapping from output frames to capture-time attitude and GPS. The launch specification table omits this later addition. |
| Standard INSP photo | 55 MP and 14 MP; INSP export workflow | JPEG RGB INSP becomes RGB16 TIFF with GPano XMP and available ICC. Real samples tested are 7680×3840 JPEG-based INSP; this does not qualify every advertised photo resolution. |
| HDR photo, burst and AEB | Listed photo modes | **Grouped processing not implemented.** Needs grouping/exposure metadata and real captures to test complete groups, motion and exposure merging. A single processed TIFF must not be presented as a developed HDR/AEB set. |
| DNG | Listed photo format | **RAW development not implemented.** Needs genuine A1 DNGs to establish mosaic layout, black/white levels, white balance, color matrices, lens geometry and metadata linkage. |
| Log or HDR video | No confirmation in official sources checked | Do not infer these from Insta360 X-series features or shared Studio enums. Explicit Log/HDR/higher-depth sources are rejected until their color pipeline is qualified. HDR photos and the goggles' HDR display are separate capabilities. |
| Recorded audio | Vision goggles document local audio with screen recording | Tested drone originals have no audio. The CLI rejects sound-bearing INSV instead of discarding sound. Future goggles/external soundtrack import needs explicit synchronization and trimming; it must not imply the drone records ambient audio. |

Sources: [A1 specifications](https://www.antigravity.tech/us/drone/antigravity-a1/specs),
[spring update](https://www.antigravity.tech/cy/blog/VR-Drones/a1-new-features-update),
[Vision goggles audio](https://www.antigravity.tech/ro/goggles/antigravity-vision?from=nav).
The spring update also describes generated sound effects; those are not captured audio.

Standard-mode profile tests include the integer rates above and 24000/1001,
30000/1001 and 60000/1001 where appropriate. These use synthetic stream metadata,
not hardware captures at every rate. Our current private audit covers ten standard
A1 video originals and two standard INSP photos; it contains no slow-motion,
timelapse, DNG or grouped-photo originals.

## Development checks after 0.9.0

`inspect` now reports `recording_mode`: a readable name, the numeric declarations
and a qualification status. The file-group type is metadata field 26, nested
field 1; UAV camera mode is field 153. Standard video and photo identifiers were
checked on originals. Other names were inspected in Studio's shared metadata
schema; they identify declarations, not features necessarily offered by A1.
No vendor code or binary is required or distributed.

`stitch` refuses declared slow motion, timelapse, unknown/conflicting modes or
photo captures before fitting/rendering. `photo` refuses unqualified grouped
modes. Declared HDR and higher precision require a qualified color path even if
pixel tags look like SDR. A present nominal capture rate must agree with playback
rate, allowing the normal 1000/1001 convention.

Absent mode fields remain `unspecified`, preserving compatibility with earlier
supported files without guessing a label. Pixel, geometry and timing checks still
apply. This prevents incorrect processing; **it does not implement missing modes**.

To qualify another mode, retain an untouched A1 original, firmware version and
capture settings; compare a source-mapped interval with Studio. Check frame count,
playback duration, capture-time poses, pilot path, seams and color. For photos,
include every capture-group member and its DNG/INSP companions. Keep private media
and camera-specific metadata outside this repository; public fixtures are synthetic.
