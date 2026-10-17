#include "lp2/rtp_jpeg.hpp"

#include <algorithm>
#include <cstring>
#include <limits>

#include "lp2/jpeg_rtp_inspector.hpp"
#include "lp2/rfc2435_huffman.hpp"

namespace lp2 { namespace rtpjpeg {
namespace {
std::uint16_t read16(const unsigned char* p) {
    return static_cast<std::uint16_t>((p[0] << 8) | p[1]);
}
std::uint32_t read32(const unsigned char* p) {
    return (std::uint32_t(p[0]) << 24) | (std::uint32_t(p[1]) << 16) |
           (std::uint32_t(p[2]) << 8) | p[3];
}
void put16(std::vector<unsigned char>& p, std::uint16_t v) {
    p.push_back(static_cast<unsigned char>(v >> 8));
    p.push_back(static_cast<unsigned char>(v));
}
void put32(std::vector<unsigned char>& p, std::uint32_t v) {
    p.push_back(static_cast<unsigned char>(v >> 24));
    p.push_back(static_cast<unsigned char>(v >> 16));
    p.push_back(static_cast<unsigned char>(v >> 8));
    p.push_back(static_cast<unsigned char>(v));
}
void marker(std::vector<unsigned char>& p, unsigned char code,
            const unsigned char* body, std::size_t length) {
    p.push_back(0xff); p.push_back(code);
    put16(p, static_cast<std::uint16_t>(length + 2));
    p.insert(p.end(), body, body + length);
}
}

bool extract_type1(const unsigned char* jpeg, std::size_t size,
                   Image& image, std::string& reason)
{
    const JpegRtpReport report = inspect_jpeg_for_rtp(jpeg, size);
    if (!report.rtp_jpeg_eligible || report.rtp_type != 1 ||
        report.restart_interval != 0 || report.scan_end > size ||
        report.scan_start >= report.scan_end) {
        reason = report.reasons.empty() ? "not baseline type 1 without restart"
                                        : report.reasons.front();
        return false;
    }
    const std::size_t scan_size = report.scan_end - report.scan_start;
    if (scan_size > kScanMax || (scan_size + 1179) / 1180 > kFragmentsMax ||
        report.width == 0 || report.height == 0 ||
        report.width % 8 || report.height % 8 ||
        report.width > 2040 || report.height > 2040) {
        reason = "scan or dimensions exceed RTP/JPEG type 1 limits";
        return false;
    }
    bool seen[2] = {false, false};
    for (std::size_t i = 0; i < report.quant_tables.size(); ++i) {
        const QuantTableInfo& q = report.quant_tables[i];
        if (q.id > 1 || q.precision_bits != 8 || q.values.size() != 64 || seen[q.id]) {
            reason = "expected exactly two original 8-bit DQT tables";
            return false;
        }
        std::memcpy(image.quant[q.id], q.values.data(), 64);
        seen[q.id] = true;
    }
    if (!seen[0] || !seen[1]) {
        reason = "missing DQT 0 or 1";
        return false;
    }
    image.width = report.width; image.height = report.height;
    image.scan.assign(jpeg + report.scan_start, jpeg + report.scan_end);
    reason.clear();
    return true;
}

bool packetize(const Image& image, std::uint32_t ssrc,
               std::uint32_t timestamp, std::uint16_t& next_sequence,
               std::vector<std::vector<unsigned char> >& packets,
               std::string& reason)
{
    packets.clear();
    if (image.width == 0 || image.height == 0 || image.width > 2040 ||
        image.height > 2040 || image.width % 8 || image.height % 8 ||
        image.scan.empty() || image.scan.size() > kScanMax) {
        reason = "invalid image geometry or scan length";
        return false;
    }
    std::size_t offset = 0;
    while (offset < image.scan.size()) {
        const bool first = offset == 0;
        const std::size_t header = 12 + 8 + (first ? 4 + 128 : 0);
        const std::size_t count = std::min(image.scan.size() - offset,
                                            kDatagramMax - header);
        if (count == 0 || packets.size() >= kFragmentsMax) {
            packets.clear(); reason = "fragment limit exceeded"; return false;
        }
        std::vector<unsigned char> p;
        p.reserve(header + count);
        p.push_back(0x80); // RTP V=2, no P/X/CSRC
        p.push_back(static_cast<unsigned char>(kPayloadType |
                    (offset + count == image.scan.size() ? 0x80 : 0)));
        put16(p, next_sequence++); put32(p, timestamp); put32(p, ssrc);
        p.push_back(0); // type-specific
        p.push_back(static_cast<unsigned char>(offset >> 16));
        p.push_back(static_cast<unsigned char>(offset >> 8));
        p.push_back(static_cast<unsigned char>(offset));
        p.push_back(1); p.push_back(255); // type 1, in-band DQT
        p.push_back(static_cast<unsigned char>(image.width / 8));
        p.push_back(static_cast<unsigned char>(image.height / 8));
        if (first) {
            p.push_back(0); p.push_back(0); // MBZ, 8-bit precision
            put16(p, 128);
            p.insert(p.end(), image.quant[0], image.quant[0] + 64);
            p.insert(p.end(), image.quant[1], image.quant[1] + 64);
        }
        p.insert(p.end(), image.scan.begin() + offset,
                 image.scan.begin() + offset + count);
        packets.push_back(p);
        offset += count;
    }
    reason.clear();
    return true;
}

bool rebuild_jpeg(const Image& image, std::vector<unsigned char>& jpeg)
{
    jpeg.clear();
    if (image.width == 0 || image.height == 0 || image.width > 2040 ||
        image.height > 2040 || image.scan.empty() || image.scan.size() > kScanMax)
        return false;
    jpeg.push_back(0xff); jpeg.push_back(0xd8);
    for (unsigned int i = 0; i < 2; ++i) {
        unsigned char body[65]; body[0] = static_cast<unsigned char>(i);
        std::memcpy(body + 1, image.quant[i], 64);
        marker(jpeg, 0xdb, body, sizeof(body));
    }
    const unsigned char sof[] = {8,
        static_cast<unsigned char>(image.height >> 8),
        static_cast<unsigned char>(image.height),
        static_cast<unsigned char>(image.width >> 8),
        static_cast<unsigned char>(image.width),
        3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1};
    marker(jpeg, 0xc0, sof, sizeof(sof));
    append_rfc2435_huffman_markers(jpeg);
    const unsigned char sos[] = {3, 1, 0, 2, 0x11, 3, 0x11, 0, 63, 0};
    marker(jpeg, 0xda, sos, sizeof(sos));
    jpeg.insert(jpeg.end(), image.scan.begin(), image.scan.end());
    jpeg.push_back(0xff); jpeg.push_back(0xd9);
    return true;
}

void Reassembler::expire(std::uint64_t now_ms)
{
    for (std::map<Key, State>::iterator it = frames_.begin(); it != frames_.end();) {
        if (now_ms >= it->second.last_ms && now_ms - it->second.last_ms >= 500) {
            ++stats_.incomplete_timeouts;
            it = frames_.erase(it);
        } else ++it;
    }
}

bool Reassembler::accept(const unsigned char* p, std::size_t n,
                         std::uint64_t now_ms,
                         std::vector<unsigned char>& completed_jpeg)
{
    completed_jpeg.clear(); ++stats_.received_packets; expire(now_ms);
    if (p == nullptr || n < 21 || n > kDatagramMax || p[0] != 0x80 ||
        (p[1] & 0x7f) != kPayloadType || p[12] != 0 || p[16] != 1 ||
        p[17] != 255 || p[18] == 0 || p[19] == 0) {
        ++stats_.invalid_packets; return false;
    }
    const std::uint32_t offset = (std::uint32_t(p[13]) << 16) |
        (std::uint32_t(p[14]) << 8) | p[15];
    std::size_t at = 20;
    unsigned char quant[2][64] = {{0}};
    if (offset == 0) {
        if (n < at + 4 + 128 || p[at] != 0 || p[at+1] != 0 ||
            read16(p + at + 2) != 128) {
            ++stats_.invalid_packets; return false;
        }
        std::memcpy(quant, p + at + 4, 128);
        at += 132;
    }
    const std::size_t payload = n - at;
    if (payload == 0 || payload > kScanMax ||
        offset > kScanMax - payload ||
        offset + payload > (1U << 24)) {
        ++stats_.invalid_packets; return false;
    }
    const Key key = {read32(p + 8), read32(p + 4)};
    std::map<Key, State>::iterator found = frames_.find(key);
    if (found == frames_.end()) {
        if (frames_.size() >= kActiveFramesMax) {
            ++stats_.capacity_drops; return false;
        }
        State state; state.width = p[18] * 8U; state.height = p[19] * 8U;
        state.last_ms = now_ms;
        found = frames_.insert(std::make_pair(key, state)).first;
    }
    State& state = found->second;
    if (state.width != p[18] * 8U || state.height != p[19] * 8U ||
        (state.has_end && offset + payload > state.end_offset) ||
        (offset == 0 && state.has_quant &&
         std::memcmp(state.quant, quant, 128) != 0)) {
        ++stats_.invalid_packets; return false;
    }
    if (offset == 0) {
        std::memcpy(state.quant, quant, 128); state.has_quant = true;
    }
    const std::map<std::uint32_t, std::vector<unsigned char> >::iterator next =
        state.fragments.lower_bound(offset);
    if (next != state.fragments.end() && next->first == offset) {
        const bool stored_last = state.has_end &&
            state.end_offset == offset + payload;
        if (stored_last != bool(p[1] & 0x80)) {
            ++stats_.invalid_packets; return false;
        }
        if (next->second.size() == payload &&
            std::memcmp(next->second.data(), p + at, payload) == 0) {
            ++stats_.duplicate_fragments; return false;
        }
        ++stats_.invalid_packets; return false;
    }
    if (next != state.fragments.end() && offset + payload > next->first) {
        ++stats_.invalid_packets; return false;
    }
    if (next != state.fragments.begin()) {
        std::map<std::uint32_t, std::vector<unsigned char> >::iterator prev = next;
        --prev;
        if (prev->first + prev->second.size() > offset) {
            ++stats_.invalid_packets; return false;
        }
    }
    if (state.fragments.size() >= kFragmentsMax ||
        state.bytes > kScanMax - payload) {
        ++stats_.capacity_drops; return false;
    }
    if (p[1] & 0x80) {
        if (state.has_end && state.end_offset != offset + payload) {
            ++stats_.invalid_packets; return false;
        }
        if (!state.fragments.empty()) {
            std::map<std::uint32_t, std::vector<unsigned char> >::const_iterator last =
                state.fragments.end(); --last;
            if (last->first + last->second.size() > offset + payload) {
                ++stats_.invalid_packets; return false;
            }
        }
        state.has_end = true; state.end_offset = offset + payload;
    }
    state.fragments[offset] = std::vector<unsigned char>(p + at, p + n);
    state.bytes += payload; state.last_ms = now_ms;
    if (!state.has_quant || !state.has_end || state.bytes != state.end_offset)
        return false;
    Image image; image.width = state.width; image.height = state.height;
    std::memcpy(image.quant, state.quant, 128);
    std::size_t cursor = 0;
    for (std::map<std::uint32_t, std::vector<unsigned char> >::const_iterator
         it = state.fragments.begin(); it != state.fragments.end(); ++it) {
        if (it->first != cursor) return false;
        image.scan.insert(image.scan.end(), it->second.begin(), it->second.end());
        cursor += it->second.size();
    }
    if (cursor != state.end_offset || !rebuild_jpeg(image, completed_jpeg) ||
        !inspect_jpeg_for_rtp(completed_jpeg.data(), completed_jpeg.size())
             .rtp_jpeg_eligible) {
        ++stats_.jpeg_validation_failures;
        completed_jpeg.clear(); frames_.erase(found); return false;
    }
    ++stats_.completed_frames;
    frames_.erase(found);
    return true;
}

} } // namespace lp2::rtpjpeg
