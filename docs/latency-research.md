# Latency research: measurements and boundaries

The independent M8 experiments are documented here rather than bundling duplicate
overlays whose test drivers require private binaries. They did not replace the
M7.2/M7.4 deployed baseline.

## Observations, not attribution

- Visible scene/screen timer trial: approximately350-400ms, preliminary only.
- User-reported experimental averages: capture queue0.100ms, sender queue0.071ms,
  complete RTP sink call7.252ms;469/469 frames submitted. The complete raw bundle
  for that run is not supplied. These values do not identify the whole-path bottleneck.
- Latest-frame selection triggered only occasionally and did not show a meaningful
  improvement. No success claim is based on subjective smoothness or a new flag.

The camera-only run had300 frames,29.143fps, requested/returned mmap buffers4/4.
Of300 driver timestamps,121 met the diagnostic comparability checks and179 were
rejected as future136/backward43. The conditional121-sample average83.088ms is
not a known sensor/encoding-to-dequeue delay or83ms of removable buffering.
The underlying raw dataset is retained privately, not rewritten or zero-filled.

## Measurement boundaries

Do not subtract clocks from the board and Ubuntu without synchronization and
semantics. Even a driver-declared monotonic/SOE timestamp need not reliably mark
physical exposure/encoding completion on the old UVC stack. Four mapped buffers
do not imply four queued completed frames. Frame send budget100ms is not an
end-to-end bound. Averages from different runs/frames cannot be subtracted to
derive decoder latency.

A non-invasive method is a single recording containing both a real scene change
and the displayed response, with a verified timebase, matched events, original
data, sample count/median/tails and uncertainty. That formal quantitative result
remains optional/pending; it is not supplied by this source export.

The engineering conclusion was to keep the ownership/queue baseline unchanged
rather than invent a queue optimization unsupported by the data.
