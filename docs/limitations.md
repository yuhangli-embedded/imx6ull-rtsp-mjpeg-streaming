# Known limitations and open items

- Overall historical acceptance is CONDITIONAL PASS. M9.3 media independence is
  PASS, but its full automatic Gate is INCONCLUSIVE. Do not hide missing evidence.
- Two ffplay windows were observed to exit together when one was closed. Root
  cause remains OPEN; server process identity was stable. Headless FFmpeg tests
  do not prove a GUI/client issue was fixed or even localize its cause.
- Preliminary visible delay was approximately350-400ms. M8 did not demonstrate
  a significant end-to-end reduction. No hard latency bound or rigorous final
  scene-to-screen distribution is claimed.
- UVC input may contain malformed JPEG without error flags; strict filtering
  rejects it. Driver sequence gaps are not all proven application losses.
- UDP kernel submission is not delivery. Loss/reordering may damage a whole
  frame; severe impairment can leave the old player delayed until reconnect.
- Only up to two sessions; baseline single-scan4:2:0/standard-Huffman/no-restart
  JPEG subset. Not a complete RTSP standard implementation or general transcoder.
- No RTCP, retransmission/NACK/FEC, TCP interleaving, authentication, H.264/audio,
  Internet-facing hardening, systemd integration or kernel/driver development.
- Capture copies mmap data; RTP parsing uses vectors. Not zero-copy or globally
  allocation-free; no promise of exhaustion=0 under every possible workload.
- Watchdog checks process exit, not frozen video/RTSP/decoder health; it is not
  itself automatically respawned. Reset/manual-start lock contention is known.
- Reboot autostart was confirmed, not every abrupt-power-loss transaction or
  shutdown/runlevel/K-link ordering scenario. Unknown residual locks are not force-removed.
- Deployment requires root and specific tools including mv -T; an ash test with
  external GNU mv is not proof of pure BusyBox compatibility.
- Native tests and Poky static ABI for the replacement passed per the maintainer;
  its supplied ARM SHA-256 is recorded in validation, not independently recomputed
  in this review. Project code is MIT; RFC-derived
  parameter material retains separately documented historical terms.

These limits are part of the public presentation, not reasons to modify the
frozen implementation or relabel an experiment as successful.
