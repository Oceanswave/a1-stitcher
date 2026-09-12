# 0.5: native-resolution finishing, Metal and anchored gyro

This pass separates technical output checks, measured throughput, sampled image
agreement and motion evidence. Real recordings, per-unit profiles and private
source paths are retained outside the public repository; public tests synthesize
all media and sensor streams.

## Finishing defaults

The default sphere is 8192×4096 with native-size lens decoding. HEVC10 and ProRes
422 HQ paths decode/remap/blend at 16-bit image precision and encode at 10 bits.
The old 8-bit H.264 path remains an explicit review option. This reduces new
processing loss on the tested 8-bit SDR capture; it does not add captured dynamic
range or implement log/HDR ingest.

ProRes MOV exports include an explicit limited-range BT.709 `nclx` color box.
FFmpeg 6.1 leaves the range unspecified when reading the older MOV `nclc` box,
even when the encoder was given limited-range settings. The CLI makes that range
explicit without changing encoded pixels and rejects conflicting descriptions.
The same full encode/decode tests cover Linux FFmpeg 6.1 and macOS FFmpeg 8.1.

Cubic interpolation now replicates edge pixels instead of mixing black padding
into valid lens samples. Synthetic sub-8-bit signals survive both seam analysis
and final remapping; flow still uses a small 8-bit analysis image while final
pixels come from the full-precision lenses.

Five 90-frame native-resolution ProRes sequences from two recordings completed
full decode, frame-count, color, complete-sphere, metadata and checksum checks.
These are 3.003-second qualification sequences, not long-form finishing acceptance.
A 90-frame rapid-turn sample was compared with corresponding Studio frames at
0, 15, 32, 60 and 89. At 2048-pixel comparison width, matched-inlier median angular
errors were 0.099–0.136°, with 95th-percentile errors 0.223–0.470°. Per-frame global
alignment excludes unmatched pixels and hides global attitude differences; these
are not whole-image or motion scores. Moving comparisons use one alignment at
frame zero and preserve subsequent motion.

## Metal performance

Hardware: Apple M1 Max, 32 GPU cores, 64 GB memory. Software: Python 3.12.14,
NumPy 2.5.3, SciPy 1.18.1, OpenCV 5.0.0 and FFmpeg 8.1.2. Each test uses the same
cached 3840×3840 lens pair, 16-bit processing, flow seam, a nontrivial rotation,
21.325 ms sensor readout and four CPU threads. The table is the median of two
warm iterations after one warm-up, using a fresh renderer for each backend/size.

| Full sphere | CPU seconds/frame | Metal seconds/frame | Stitch-stage speedup |
| --- | ---: | ---: | ---: |
| 2048×1024 | 1.050 | 0.206 | 5.1× |
| 4096×2048 | 4.012 | 0.290 | 13.8× |
| 8192×4096 | 13.761 | 0.444 | 31.0× |

These times include CPU seam analysis, transfers, projection, rolling-shutter
mapping and interpolation/blending. They exclude bridge compilation, source
video decoding, encoding, muxing, checksum and full-decode verification. The
small warm sample is a useful controlled comparison, not a statistical guarantee
for arbitrary footage, thermal conditions or hardware.

An additional **complete-job** test ran the same three source frames sequentially
through both backends: native-resolution 8K, ProRes 422 HQ, flow and sensor-row
correction. External process wall time was **35.73 seconds CPU versus 9.34 seconds
Metal, a 3.8× speedup**. Each process included startup; Metal included bridge/kernel
initialization. This tiny job is dominated by overhead and is not a sustained
throughput benchmark. A separate 90-frame 8K ProRes Metal job completed in
74.17 seconds including full verification. No real-time 8K export is claimed.

CPU/Metal output is close, not bit-identical. On the real lens-pair tests, mean
absolute channel differences were 0.120 of an 8-bit level at all sizes; the 99th
percentile was at most 0.794, the 99.9th at most 1.320, and the maximum at most
3.179. These compare unencoded 16-bit images, scaled by 257 for readability.
Synthetic hardware tests additionally cover uint8/uint16, all three seam modes,
with/without sensor-row correction, temporal state and closed-renderer errors.

Metal is selected automatically when preflight succeeds, with CPU fallback and
its reason recorded. `--backend metal` requires the GPU; `--backend cpu` forces
the reference path. The shader implements the same lens/row/seam model; it does
not use vendor libraries, download a binary or synthesize detail. Native source
ships in the wheel and is included in the processing fingerprint.

## Raw gyro and motion

A rigid sensor-axis rotation, bias and timestamp offset fitted at 2 Hz low-pass
transferred from one recording to another at **0.861°/s RMS**. Training and held-out
blocks were 0.877 and 0.901°/s RMS. The fit enforces proper rotation and rejects
underexcited motion, unsupported sensor formats, saturation, gaps and failed
residual bounds. Per-unit constants and telemetry are not published.

The optional `--gyro-profile` path integrates raw gyro at up to 1 ms steps, bounded
by recorded-attitude anchors. Anchoring at every approximately 20 ms attitude
sample reintroduced some high-frequency attitude error. The optional mode now
uses **0.1-second anchors**, adjustable with `--gyro-anchor-seconds 0.02–1`.
Wider spacing permits more inter-anchor drift; it is not inherently better.
Recorded attitude remains the ordinary default because gyro use requires a valid
per-unit profile and shot-specific image qualification.

Fixed 90° reframes from complete 8K native renders were measured over 90 frames.
The diagnostic tracks background features, fits robust frame-to-frame affine
motion and measures the change in that motion at 960×540. It includes parallax,
tracking noise and translational acceleration; it is not an absolute shake or
cinematic-quality score.

| Recording / path | Median background acceleration, px | 95th percentile, px |
| --- | ---: | ---: |
| Rapid turn, Studio reference | 0.407 | 2.048 |
| Rapid turn, recorded attitude | 1.580 | 14.185 |
| Rapid turn, gyro with 20 ms anchors | 1.309 | 10.581 |
| Rapid turn, gyro with 100 ms anchors | 0.552 | 3.059 |
| Second recording, recorded attitude | 1.386 | 3.362 |
| Second recording, same gyro profile / 100 ms anchors | 0.472 | 2.015 |

Relative to recorded attitude, 100 ms gyro anchors reduced this diagnostic by
65% at the median / 78% at the 95th percentile on the rapid turn, and 66% / 40%
on the second recording. This is evidence of improvement on those two short
intervals. It does not prove correction of all vibration frequencies, long-duration
drift, exposure timing or all scenes. Sensor-row correction still uses a locally
constant angular velocity, not a fully varying per-row trajectory. Captured motion
blur, nearby occlusion, propellers and flare remain visible in difficult scenes.

## Acceptance and regression coverage

The hardware-enabled suite passed 213 tests with 89.83% Python coverage. Without
GPU access, 201 pass and 12 hardware cases are explicitly skipped. Checks include
FFmpeg encodes/full decode, codec/pixel-format verification, native-size defaults,
batch profile paths/collision protection, synthetic gyro fitting and vibration,
CPU/GPU parity, no-overwrite publication, receipts and GPX behavior.

The wheel includes the native source; installed-wheel execution is checked outside
the source checkout before release. Documentation and option references are
reviewed against CLI help before tagging. Tests and successful playback do not
stand in for continuous perceptual viewing. Unreviewed outputs remain marked for
motion review in the private director workflow, which retains prior-event usage
and original-frame provenance when handing selected media to Resolve.
