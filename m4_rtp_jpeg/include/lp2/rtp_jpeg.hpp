#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace lp2 { namespace rtpjpeg {

// 1200-byte UDP payload, leaving IPv4/UDP overhead below a 1500-byte MTU.
const std::size_t kDatagramMax = 1200;
const std::size_t kScanMax = 1024 * 1024;
const std::size_t kFragmentsMax = 1024;
const std::size_t kActiveFramesMax = 8;
const std::uint8_t kPayloadType = 96;

struct Image {
    unsigned int width = 0;
    unsigned int height = 0;
    unsigned char quant[2][64] = {{0}};
    std::vector<unsigned char> scan;
};

// Uses the M4.2B parser. Never accepts a whole JFIF as an RTP scan.
bool extract_type1(const unsigned char* jpeg, std::size_t size,
                   Image& image, std::string& reason);
bool packetize(const Image& image, std::uint32_t ssrc,
               std::uint32_t timestamp, std::uint16_t& next_sequence,
               std::vector<std::vector<unsigned char> >& packets,
               std::string& reason);
bool rebuild_jpeg(const Image& image, std::vector<unsigned char>& jpeg);

struct ReceiverStats {
    std::uint64_t received_packets = 0;
    std::uint64_t invalid_packets = 0;
    std::uint64_t duplicate_fragments = 0;
    std::uint64_t incomplete_timeouts = 0;
    std::uint64_t capacity_drops = 0;
    std::uint64_t completed_frames = 0;
    std::uint64_t jpeg_validation_failures = 0;
};

class Reassembler {
public:
    // now_ms is a monotonic time supplied by the caller, for deterministic tests.
    bool accept(const unsigned char* packet, std::size_t length,
                std::uint64_t now_ms, std::vector<unsigned char>& completed_jpeg);
    void expire(std::uint64_t now_ms);
    std::size_t active_frames() const { return frames_.size(); }
    const ReceiverStats& stats() const { return stats_; }
private:
    struct Key {
        std::uint32_t ssrc, timestamp;
        bool operator<(const Key& other) const {
            return ssrc < other.ssrc ||
                (ssrc == other.ssrc && timestamp < other.timestamp);
        }
    };
    struct State {
        unsigned int width = 0, height = 0;
        bool has_quant = false, has_end = false;
        unsigned char quant[2][64] = {{0}};
        std::size_t end_offset = 0, bytes = 0;
        std::uint64_t last_ms = 0;
        std::map<std::uint32_t, std::vector<unsigned char> > fragments;
    };
    std::map<Key, State> frames_;
    ReceiverStats stats_;
};

} } // namespace lp2::rtpjpeg
