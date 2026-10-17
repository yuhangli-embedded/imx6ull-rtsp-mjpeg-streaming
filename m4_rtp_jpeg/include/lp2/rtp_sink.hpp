#pragma once

#include <cstdint>
#include <string>

#include "lp2/media_sink.hpp"

namespace lp2 {

class RtpSink : public IMediaSink {
public:
    RtpSink(const std::string& target_ip, std::uint16_t port,
            unsigned int gap_us, unsigned int budget_ms,
            std::uint8_t payload_type = 96,
            std::uint16_t local_rtp_port = 0);
    ~RtpSink();
    bool initialize();
    bool consume(const Frame& frame) override;
    // M5 fan-out calls this only after its shared consumer has performed the
    // strict JPEG check once. The existing consume() path remains unchanged.
    bool consume_prevalidated(const Frame& frame);
    std::uint64_t incompatible_frames() const { return incompatible_frames_; }
    std::uint64_t fully_submitted_frames() const { return submitted_frames_; }
    std::uint64_t failed_frames() const { return failed_frames_; }
    std::uint64_t submitted_datagrams() const { return datagrams_; }
    std::uint64_t submitted_bytes() const { return bytes_; }
    std::uint64_t budget_failures() const { return budget_failures_; }
    std::uint64_t eagain_events() const { return eagain_events_; }
    int send_buffer_bytes() const { return send_buffer_bytes_; }
    std::uint16_t local_rtp_port() const { return local_rtp_port_; }
    const std::string& error() const { return error_; }
private:
    std::string target_ip_;
    std::uint16_t port_;
    unsigned int gap_us_, budget_ms_;
    std::uint8_t payload_type_;
    std::uint16_t local_rtp_port_;
    int fd_ = -1, send_buffer_bytes_ = 0;
    std::uint32_t target_addr_ = 0, ssrc_ = 0;
    std::uint16_t sequence_ = 0;
    std::uint64_t incompatible_frames_ = 0, submitted_frames_ = 0,
                  failed_frames_ = 0, datagrams_ = 0, bytes_ = 0,
                  eagain_events_ = 0, budget_failures_ = 0;
    std::string error_;
};

} // namespace lp2
