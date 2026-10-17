#include "lp2/rtp_sink.hpp"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include "lp2/jpeg_validator.hpp"
#include "lp2/rtp_jpeg.hpp"
#include "lp2/rtp_payload_type.hpp"

namespace lp2 {

RtpSink::RtpSink(const std::string& ip, std::uint16_t port,
                 unsigned int gap_us, unsigned int budget_ms,
                 std::uint8_t payload_type, std::uint16_t local_rtp_port)
    : target_ip_(ip), port_(port), gap_us_(gap_us), budget_ms_(budget_ms)
    , payload_type_(payload_type), local_rtp_port_(local_rtp_port)
{
    const std::uint64_t seed = static_cast<std::uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count()) ^
        static_cast<std::uint64_t>(getpid());
    ssrc_ = static_cast<std::uint32_t>(seed ^ (seed >> 32));
    sequence_ = static_cast<std::uint16_t>(seed >> 16);
}

RtpSink::~RtpSink() { if (fd_ >= 0) close(fd_); }

bool RtpSink::initialize()
{
    struct in_addr address {};
    if (port_ == 0 || inet_pton(AF_INET, target_ip_.c_str(), &address) != 1) {
        error_ = "RTP target must be numeric IPv4 plus nonzero port";
        return false;
    }
    target_addr_ = address.s_addr;
    fd_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) { error_ = std::strerror(errno); return false; }
    if (local_rtp_port_ != 0) {
        struct sockaddr_in local {};
        local.sin_family = AF_INET;
        local.sin_addr.s_addr = htonl(INADDR_ANY);
        local.sin_port = htons(local_rtp_port_);
        if (bind(fd_, reinterpret_cast<const struct sockaddr*>(&local),
                 sizeof(local)) < 0) {
            error_ = std::string("RTP bind: ") + std::strerror(errno);
            return false;
        }
    }
    const int flags = fcntl(fd_, F_GETFL, 0);
    if (flags < 0 || fcntl(fd_, F_SETFL, flags | O_NONBLOCK) < 0) {
        error_ = "RTP O_NONBLOCK failed"; return false;
    }
    const int requested = 1024 * 1024;
    if (setsockopt(fd_, SOL_SOCKET, SO_SNDBUF, &requested, sizeof(requested)) < 0) {
        error_ = "RTP SO_SNDBUF failed"; return false;
    }
    socklen_t len = sizeof(send_buffer_bytes_);
    if (getsockopt(fd_, SOL_SOCKET, SO_SNDBUF, &send_buffer_bytes_, &len) < 0) {
        error_ = "RTP getsockopt SO_SNDBUF failed"; return false;
    }
    return true;
}

bool RtpSink::consume(const Frame& frame)
{
    error_.clear();
    if (!JpegValidator::validate(frame).valid) {
        ++failed_frames_; error_ = "invalid JPEG or RTP socket unavailable";
        return false;
    }
    return consume_prevalidated(frame);
}

bool RtpSink::consume_prevalidated(const Frame& frame)
{
    error_.clear();
    if (fd_ < 0) {
        ++failed_frames_; error_ = "invalid JPEG or RTP socket unavailable";
        return false;
    }
    rtpjpeg::Image image;
    std::string reason;
    if (!rtpjpeg::extract_type1(frame.storage.data(), frame.size, image, reason)) {
        ++incompatible_frames_; error_ = "RTP-incompatible JPEG: " + reason;
        return false;
    }
    const std::uint64_t capture_us = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            frame.application_capture_time.time_since_epoch()).count());
    const std::uint32_t timestamp = static_cast<std::uint32_t>(
        (capture_us / 1000) * 90 + ((capture_us % 1000) * 90) / 1000);
    std::vector<std::vector<unsigned char> > packets;
    if (!rtpjpeg::packetize(image, ssrc_, timestamp, sequence_, packets,
                            reason) ||
        (payload_type_ != rtpjpeg::kPayloadType &&
         !rtpjpeg::set_payload_type(packets, payload_type_))) {
        ++failed_frames_; error_ = "RTP packetizer: " + reason; return false;
    }
    struct sockaddr_in destination {};
    destination.sin_family = AF_INET;
    destination.sin_port = htons(port_);
    destination.sin_addr.s_addr = target_addr_;
    typedef std::chrono::steady_clock Clock;
    const Clock::time_point deadline = Clock::now() +
        std::chrono::milliseconds(budget_ms_);
    Clock::time_point next_send = Clock::now();
    std::size_t completed_packets = 0;
    for (std::size_t i = 0; i < packets.size(); ++i) {
        if (gap_us_ && i != 0) {
            next_send += std::chrono::microseconds(gap_us_);
            if (next_send >= deadline) break;
            std::this_thread::sleep_until(next_send);
        }
        bool submitted = false;
        unsigned int would_block_retries = 0;
        while (Clock::now() < deadline) {
            const ssize_t sent = sendto(fd_, packets[i].data(), packets[i].size(), 0,
                reinterpret_cast<const struct sockaddr*>(&destination),
                sizeof(destination));
            if (sent == static_cast<ssize_t>(packets[i].size())) {
                ++datagrams_; bytes_ += packets[i].size(); submitted = true; break;
            }
            if (sent < 0 && errno == EINTR) continue;
            if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                ++eagain_events_;
                if (++would_block_retries > 8) {
                    error_ = "RTP EAGAIN retry limit reached";
                    break;
                }
                const Clock::time_point now = Clock::now();
                const long left = std::chrono::duration_cast<
                    std::chrono::milliseconds>(deadline - now).count();
                if (left <= 0) break;
                struct pollfd waitfd {}; waitfd.fd = fd_; waitfd.events = POLLOUT;
                const int ready = poll(&waitfd, 1, static_cast<int>(left));
                if (ready > 0 && (waitfd.revents & POLLOUT) &&
                    !(waitfd.revents & (POLLERR | POLLHUP | POLLNVAL))) continue;
                if (ready < 0 && errno == EINTR) continue;
                break;
            }
            error_ = sent < 0 ? std::strerror(errno) : "short UDP datagram";
            break;
        }
        if (!submitted) {
            ++failed_frames_;
            if (error_.empty()) {
                error_ = "RTP per-frame send budget expired";
                ++budget_failures_;
            }
            return false;
        }
        ++completed_packets;
    }
    if (completed_packets != packets.size()) {
        ++failed_frames_; error_ = "RTP per-frame send budget expired";
        ++budget_failures_;
        return false;
    }
    ++submitted_frames_;
    return true;
}

} // namespace lp2
