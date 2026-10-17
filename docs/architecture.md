# Architecture and ownership

The public tree keeps selected original module names so relative includes are
auditable. It is a self-contained source tree, not an overlay requiring a private
parent checkout. The media target is `lp2_m5_rtsp_server`.

## Data plane

1. V4L2 negotiates MJPEG/size/fps and requests four mmap buffers, using the actual
   returned count. Four buffers do not imply four frames of fixed latency.
2. Capture DQBUFs, acquires an application Frame, copies bytesused, and immediately
   QBUFs the driver buffer. No asynchronous sender receives an mmap pointer.
3. A capacity-four capture queue drops oldest when full; the consumer validates
   size >= 4, initial FF D8 and final effective bytes FF D9.
4. Invalid input is counted separately from queue backpressure and returned.
   Valid frames are offered to the playing sessions with one reference per owner.
5. Each session has a capacity-two queue, sender, sink/socket, SSRC and RTP state.
   A sender or its queue eviction releases only that session's reference.
6. The last reference returns the fixed pool slot. Pool capacity remains six.

FramePool storage is acquired before validation, not allocated after the filter.
The [README diagram](../README.md) shows it as a resource, with references returning.
Pool grant/release operations are mutex-protected. There is no per-frame second
payload copy for fan-out, but capture's mmap-to-owned-buffer copy is intentional.
The RTP path still allocates image/packet vectors.

## RTP/JPEG

Only complete strict JPEGs that pass the JPEG/RTP compatibility parser can be
packetized: baseline 8-bit, single interleaved scan, 4:2:0, standard Huffman,
two 8-bit DQT tables and no DRI/RST. Entropy scan bytes, not the JFIF envelope,
are fragmented. Type=1, Q=255, both DQT tables in the first packet; packet size
<=1200 bytes including RTP headers. The final packet has marker=1.

Timestamp derives from the application's capture clock in 90 kHz units; it is
not a synchronized sensor exposure timestamp or a board-to-host latency clock.
M5 PT=26 is patched into the same RTP/JPEG implementation whose M4 tests retain PT=96.
Nonblocking sendto, pacing and EAGAIN retry have a frame send budget. That budget
starts after preparation and is not an end-to-end bound.

## Control and operations

RTSP TCP handles OPTIONS/DESCRIBE/SETUP/PLAY/TEARDOWN; UDP transports only, at most
two sessions. EOF releases a session without requiring TEARDOWN. The first PLAY
starts streaming. Server RTP/RTCP port pairs are 5004/5005 and 5006/5007; RTCP ports
are reserved, but RTCP reporting is not implemented.

Capture/consumer do not wait for network sending. A session closes its own queue,
joins its sender and drains references; global shutdown stops capture, wakes queues,
joins workers and returns resources. Historical ownership gates check references,
capture acquire/return, pool availability and queue depths together.

SysVinit and the independent watchdog manage process lifetime, not individual
frames. See [deployment](deployment.md). The historical GUI disconnect symptom
remains [OPEN](limitations.md), despite source-level isolation and headless evidence.
