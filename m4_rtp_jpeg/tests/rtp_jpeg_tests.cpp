#include <algorithm>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

#include "lp2/jpeg_rtp_inspector.hpp"
#include "lp2/rtp_jpeg.hpp"

namespace {
std::uint32_t be32(const unsigned char* p) {
    return (std::uint32_t(p[0]) << 24) | (std::uint32_t(p[1]) << 16) |
           (std::uint32_t(p[2]) << 8) | p[3];
}
void check(bool value, const char* why) {
    if (!value) { std::cerr << "FAIL: " << why << '\n'; std::exit(1); }
}
}

int main(int argc, char** argv)
{
    check(argc == 2, "fixture path required");
    std::ifstream input(argv[1], std::ios::binary);
    check(input.good(), "synthetic JPEG fixture unavailable");
    const std::vector<unsigned char> source(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    check(!source.empty(), "synthetic JPEG fixture empty");
    lp2::rtpjpeg::Image image;
    std::string reason;
    check(lp2::rtpjpeg::extract_type1(source.data(), source.size(), image, reason),
          reason.c_str());
    const lp2::JpegRtpReport original = lp2::inspect_jpeg_for_rtp(
        source.data(), source.size());
    check(image.scan.size() == original.scan_end - original.scan_start &&
        std::equal(image.scan.begin(), image.scan.end(),
                   source.begin() + original.scan_start),
        "scan bytes must match original synthetic JPEG exactly");
    for (std::size_t t = 0; t < original.quant_tables.size(); ++t)
        check(std::equal(original.quant_tables[t].values.begin(),
                         original.quant_tables[t].values.end(),
                         image.quant[original.quant_tables[t].id]),
              "DQT bytes must match original synthetic JPEG exactly");

    std::uint16_t sequence = 65530;
    std::vector<std::vector<unsigned char> > packets;
    check(lp2::rtpjpeg::packetize(image, 0x12345678, 90000, sequence,
                                  packets, reason), "packetization");
    check(packets.size() > 2, "synthetic frame must be multi-fragment");
    std::vector<unsigned char> independent_scan;
    for (std::size_t i = 0; i < packets.size(); ++i) {
        const std::vector<unsigned char>& p = packets[i];
        check(p.size() <= 1200 && p[0] == 0x80 && (p[1] & 0x7f) == 96 &&
            be32(p.data() + 4) == 90000 && be32(p.data() + 8) == 0x12345678 &&
            p[16] == 1 && p[17] == 255 &&
            p[18] == image.width / 8 && p[19] == image.height / 8,
            "independent wire header check");
        const std::size_t offset = (std::size_t(p[13]) << 16) |
            (std::size_t(p[14]) << 8) | p[15];
        check(offset == independent_scan.size(), "wire offsets contiguous");
        check(bool(p[1] & 0x80) == (i + 1 == packets.size()),
              "marker only on final packet");
        check(std::uint16_t((p[2] << 8) | p[3]) ==
              std::uint16_t(65530 + i), "RTP sequence must increment");
        const std::size_t at = i == 0 ? 152 : 20;
        if (i == 0) {
            check(p[20] == 0 && p[21] == 0 && p[22] == 0 && p[23] == 128 &&
                std::equal(p.begin() + 24, p.begin() + 88, image.quant[0]) &&
                std::equal(p.begin() + 88, p.begin() + 152, image.quant[1]),
                "first packet must carry both original DQT tables");
        }
        independent_scan.insert(independent_scan.end(), p.begin() + at, p.end());
    }
    check(independent_scan == image.scan, "wire scan differs from synthetic scan");
    lp2::rtpjpeg::Reassembler receiver;
    std::vector<unsigned char> rebuilt;
    // Reverse order puts the marker packet before the quantization packet.
    for (std::size_t i = packets.size(); i-- > 0;) {
        if (i == packets.size() / 2) {
            check(!receiver.accept(packets[i].data(), packets[i].size(), 1, rebuilt),
                  "early completion");
            check(!receiver.accept(packets[i].data(), packets[i].size(), 1, rebuilt),
                  "duplicate completed frame");
        } else {
            receiver.accept(packets[i].data(), packets[i].size(), 1, rebuilt);
        }
    }
    check(receiver.stats().completed_frames == 1 &&
          receiver.stats().duplicate_fragments == 1 && !rebuilt.empty(),
          "out-of-order duplicate reassembly");
    lp2::rtpjpeg::Image roundtrip;
    check(lp2::rtpjpeg::extract_type1(rebuilt.data(), rebuilt.size(),
                                      roundtrip, reason), "rebuilt JPEG parse");
    check(roundtrip.scan == image.scan &&
          std::equal(&roundtrip.quant[0][0], &roundtrip.quant[0][0] + 128,
                     &image.quant[0][0]), "reassembled scan/DQT mismatch");

    // Single-packet small scan exercises first-packet Q header and marker.
    lp2::rtpjpeg::Image small = image;
    small.scan.assign(image.scan.begin(), image.scan.begin() + 10);
    std::vector<std::vector<unsigned char> > single;
    check(lp2::rtpjpeg::packetize(small, 1, 2, sequence, single, reason) &&
          single.size() == 1 && (single[0][1] & 0x80), "single packet");
    lp2::rtpjpeg::Reassembler one_packet;
    check(one_packet.accept(single[0].data(), single[0].size(), 2, rebuilt) &&
          one_packet.stats().completed_frames == 1,
          "single-packet end-to-end reassembly");
    // The truncated synthetic scan is only used for packet boundaries, not
    // as evidence that a decoder accepts an incomplete entropy bitstream.

    lp2::rtpjpeg::Reassembler loss;
    for (std::size_t i = 0; i + 1 < packets.size(); ++i) {
        if (i == 3) continue;
        loss.accept(packets[i].data(), packets[i].size(), 10, rebuilt);
    }
    loss.expire(510);
    check(loss.stats().completed_frames == 0 &&
          loss.stats().incomplete_timeouts == 1 && loss.active_frames() == 0,
          "missing fragment timeout/capacity recovery");
    std::vector<unsigned char> bad = packets[0];
    bad[0] = 0x40;
    loss.accept(bad.data(), bad.size(), 511, rebuilt);
    check(loss.stats().invalid_packets == 1, "bad RTP version");
    bad = packets[0]; bad[22] = 0; bad[23] = 0;
    loss.accept(bad.data(), bad.size(), 511, rebuilt);
    check(loss.stats().invalid_packets == 2, "Q=255 zero table length rejected");
    bad = packets[1]; bad[13] = 0x10; // offset > 1 MiB limit
    loss.accept(bad.data(), bad.size(), 511, rebuilt);
    check(loss.stats().invalid_packets == 3, "out-of-range offset rejected");
    bad = packets[1]; bad[15] = 1; // overlap with fragment at offset 0
    loss.accept(packets[0].data(), packets[0].size(), 512, rebuilt);
    loss.accept(bad.data(), bad.size(), 512, rebuilt);
    check(loss.stats().invalid_packets >= 4, "overlap rejected");
    lp2::rtpjpeg::Reassembler capacity;
    for (unsigned int i = 0; i < lp2::rtpjpeg::kActiveFramesMax + 1; ++i) {
        std::vector<unsigned char> partial = packets[0];
        partial[7] = static_cast<unsigned char>(i);
        capacity.accept(partial.data(), partial.size(), 100, rebuilt);
    }
    check(capacity.active_frames() == lp2::rtpjpeg::kActiveFramesMax &&
          capacity.stats().capacity_drops == 1, "bounded frame slots");
    capacity.expire(600);
    check(capacity.active_frames() == 0 &&
          capacity.stats().incomplete_timeouts == lp2::rtpjpeg::kActiveFramesMax,
          "capacity returns on timeout");
    small.width = 2040; small.height = 2040;
    check(lp2::rtpjpeg::packetize(small, 1, 2, sequence, single, reason),
          "maximum representable dimensions");
    small.width = 2048;
    check(!lp2::rtpjpeg::packetize(small, 1, 2, sequence, single, reason),
          "dimension above RFC bound rejected");
    small.width = image.width; small.scan.resize(lp2::rtpjpeg::kScanMax + 1);
    check(!lp2::rtpjpeg::packetize(small, 1, 2, sequence, single, reason),
          "oversize scan rejected");
    std::cout << "PASS: synthetic JPEG scan/DQT, wire fields, multi/single,"
              << " disorder, duplicate, loss timeout, malformed and bounds\n";
}
