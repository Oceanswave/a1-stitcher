# A1 development priorities

Updated after 0.9.0 and the recording-mode audit. The product remains an independent
**Antigravity A1** preparation CLI. Creative editing and flat reframing stay in the
user's editor.

1. **Smoother original-only output.** Compare longer native-resolution intervals
   with Studio; separate vibration, horizon error and rolling shutter. Establish
   the sensor-to-image clock and mount before adding original-only row correction.
   Keep established defaults until moving comparisons demonstrate an improvement.
2. **Seams and aircraft visibility.** Improve temporal seams, moving propeller
   handling, nearby parallax and flare-aware alternate-lens selection. Validate
   complete intervals. Static masks do not prove blade removal; both-lens occlusion
   does not contain recoverable scene detail.
3. **A1 capture-mode completeness.** Qualify standard rates/codecs on real files,
   then implement capture/playback timing for slow motion and timelapse. Track
   coverage in [recording modes](recording-modes.md). Detection/rejection is not
   support for exporting a mode.
4. **Photos and metadata.** Preserve useful capture EXIF/GPS, develop A1 DNGs,
   handle HDR/AEB/burst groups and establish precise video-frame/GPX clock mapping.
   RGB16 output alone is not RAW development or HDR recovery.
5. **Optional audio.** Import explicitly synchronized goggles/external recordings
   and preserve sound if a supported original contains it. Establish actual A1
   audio sources and timing first. Do not build a speculative Log/HDR transform
   without evidence of an A1 capture mode requiring it.
6. **Efficiency when it pays off.** Remove duplicated export/batch work. This has
   lower priority than quality and mode coverage. Do not create a persistent
   decoded-media/alignment disk cache by default: users are unlikely to re-export
   often, and originals/outputs already consume substantial space.

The development version reuses each batch job's overlap alignment in memory after
preflight. Source identity, settings, alignment integrity and profiles are checked
again before rendering. Only small alignment records persist between jobs, not
decoded frames or whole-flight viewport arrays. Temporary rendering files are
removed by default; `--keep-work` is an explicit diagnostic choice. Receipts and
requested pilot/GPX companions are deliverables, not a media cache.

A real-source preflight measurement took 4.49 seconds initially and 0.22 seconds
with reused alignment, producing the same recipe. The integration test requires
three overlap fits per batch job instead of six and verifies the rendered output.
This is a setup measurement, not a claim that decoding or rendering is faster.

Outside this scope: other camera models, a flat-video exporter, a general editor
and a persistent re-export cache. A1 firmware and capture modes remain in scope.
