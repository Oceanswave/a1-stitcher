# Camera adapters and X5 ingest groundwork

The `a1-stitch` command, package identity, A1 calibration schemas, fingerprints,
render defaults and receipts remain compatible. Sphere export is still A1 only.
The development adapter registry separates a camera's input contract from its
qualified processing capabilities. It does not infer a model from `.insv`, borrow
another model's profile, or add an SDK dependency.

| Camera | Input preflight | Independent sphere export |
| --- | --- | --- |
| Antigravity A1 | Existing SDR dual-track contract and structural lens checks | Existing experimental A1 renderer, subject to normal calibration/timing checks |
| Insta360 X5 | Explicit standard-video file group, `standard` gamma, matching square H.264/H.265 tracks, full-range 8-bit SDR BT.709; optional single 48 kHz mono/stereo AAC track | Blocked pending measured X5 orientation, image timing and native-resolution motion/seam qualification |
| X6, older X-series and other models | Rejected explicitly | Rejected explicitly |

## Read-only preflight

```sh
a1-stitch preflight SOURCE.insv --redact-path --output NEW_PREFLIGHT.json
```

The report identifies the adapter, source identity, lens-track profile, audio
contract, available orientation records, and raw IMU sample cadence. A successful
`input-contract-passed` report does not render pixels or qualify stabilization,
moving seams, FlowState parity, or audio-content synchronization. In particular,
raw sensor axes are not camera orientation. X5 export remains blocked even with
`--view fixed`, `--no-stabilization`, or an A1 calibration supplied.

The raw IMU check inventories the observed indexed 20-byte layout and its clock;
it does not integrate the gyro, infer its axes, or apply a mounting rotation.
Lens geometry validation checks the observed 40-value MEI layout; it does not
prove that every distortion term or accessory configuration has been modeled.

## Frame-mapped audio companions

```sh
a1-stitch extract-audio SOURCE.insv --first-frame FIRST --frames COUNT \
  --output NEW_AUDIO.wav
```

X5 SDR ingest can export the selected interval to native-rate float32 PCM WAV
with a checksum receipt. Channels are retained. Source video/audio start times
are included in the mapping. Fractional frame rates use exact rational arithmetic
and independently rounded absolute sample boundaries, at most half a sample per
boundary. The resulting sample count and full decode are verified before
publication. Outputs and receipts must be new files; source changes invalidate
the operation. No resampling, gain adjustment, mixing or guessed padding occurs.

Audio must cover the entire selected video interval. The inspected X5 recordings
have AAC tails shorter than their video tracks: extracting the whole recording
may fail even though a shorter interval succeeds. This failure preserves the
missing-audio boundary rather than inserting silence or shifting sound. The
receipt establishes container timestamp mapping, not acoustic/visual sync.
A1's sound-bearing-original rejection remains unchanged.

## Current evidence and next qualification

Private read-only inspection found two standard X5 originals with v3 trailers,
two native 3840-square HEVC lens tracks at 30000/1001 fps, full-range SDR BT.709,
40-value lens metadata and stereo AAC. Neither has A1 records 32 or 37. Native
7680x3840 Studio references exist for known source-frame windows, but their
ClarityPlus enhancement is a comparison confounder. No reusable X5 per-unit
sensor-to-lens orientation/image-timing calibration is available. No independent
X5 candidate has completed native-resolution motion or seam review.

Further inspection recovers [recorded V6 lens/accessory parameters and exposure
clock evidence](x5-recorded-parameters.md) with `recorded-calibration`. The originals
already carry additional calibration data; interpreting and validating those
values comes before requiring manual recalibration. Parameter recovery does not
enable sphere export.
Explicit `--lens`/`--pixel` ray diagnostics now apply recorded V6 intrinsics and
the independently implemented thirteen-term distortion model to the observed
bare/centered-crop layout. They remain separate from renderer profiles and gyro
interpretation; unsupported accessories and window layouts fail.

Private PCM checks covered two source-mapped intervals (150 frames from source
frame 0, and 600 frames from source frame 89). The companions fully decoded with
240240 and 960960 samples per channel. Comparison with Studio's AAC audio found
peak waveform correlations of approximately 0.963 and 0.966, with best offsets
of approximately 23 ms and 6 ms. These differing offsets are not a qualified
sync correction and no shift is applied. Visible/audible synchronization events
are still needed; AAC priming and vendor trim behavior need investigation.

Synthetic tests exercise dispatch, explicit mode/color rejection, fractional
audio timing, absent/short/multiple audio tracks, exact decoded PCM samples,
no-clobber behavior and the X5 render gate. Private source checks are separate
from synthetic tests. Originals, metadata dumps, profiles and generated media
stay outside commits.

To enable X5 sphere export, first interpret the recorded optical/model parameters
and transfer-test the orientation/gyro convention and image clock against this
unit's existing originals. Retain
unmodified calibration recordings with stationary texture and varied three-axis
motion, capture settings and firmware. Compare at least two independent moving
recordings against source-mapped, unenhanced native Studio spheres. Review whole
intervals for horizon, rapid rotation, temporal seams, nearby objects, flare and
guards. Verify audio mapping with a visible/audible sync event in addition to
waveform comparison. Keep lens fingerprints, capture mode and timing profile
dependencies explicit. A1 profiles and upstream per-unit constants are not X5
defaults. X6 and paired-file older cameras follow separate qualification.

Official references: [Media SDK input grouping and accessory behavior](https://insta360develop.github.io/Insta360-Developer_Docs/en/x/desktop/media/)
and [SDK integration/file formats](https://onlinemanual.insta360.com/developer/en-us/resource/integration).
These document container structure; no SDK is loaded, installed or distributed.
