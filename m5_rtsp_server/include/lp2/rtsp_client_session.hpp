#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "lp2/bounded_frame_queue.hpp"
#include "lp2/fanout_frame_pool.hpp"
#include "lp2/rtp_sink.hpp"

namespace lp2 {

struct RtspClientStats {
    unsigned int artificial_send_delay_ms = 0;
    std::uint64_t play_frames_offered = 0;
    std::uint64_t sender_queue_enqueued = 0;
    std::uint64_t sender_queue_dropped = 0;
    std::uint64_t frames_dequeued_by_sender = 0;
    std::uint64_t rtp_frames_submitted = 0;
    std::uint64_t rtp_packets_sent = 0;
    std::uint64_t rtp_bytes_sent = 0;
    std::uint64_t rtp_send_failures = 0;
    std::uint64_t budget_expired_frames = 0;
    std::uint64_t rtp_incompatible_frames = 0;
    std::size_t current_sender_queue_depth = 0;
    std::size_t max_sender_queue_depth = 0;
};

class RtspClientSession {
public:
    RtspClientSession(unsigned int client_id, const std::string& session_id,
                      int control_fd, const std::string& client_ip,
                      std::uint16_t client_rtp_port,
                      std::uint16_t client_rtcp_port,
                      int rtcp_fd, std::shared_ptr<RtpSink> sink,
                      FanoutFramePool& frames,
                      unsigned int artificial_send_delay_ms);
    ~RtspClientSession();
    RtspClientSession(const RtspClientSession&) = delete;
    RtspClientSession& operator=(const RtspClientSession&) = delete;
    bool start_sender();
    void set_playing(bool playing);
    bool is_playing() const;
    // A false result leaves ownership with caller. On true, caller must
    // release the returned oldest Frame's downstream reference, if any.
    bool offer(Frame* frame, Frame*& dropped_oldest);
    RtspClientStats stop_and_join();
    const std::string& session_id() const { return session_id_; }
    unsigned int client_id() const { return client_id_; }
    int control_fd() const { return control_fd_; }
    const std::string& client_ip() const { return client_ip_; }
    std::uint16_t client_rtp_port() const { return client_rtp_port_; }
    std::uint16_t client_rtcp_port() const { return client_rtcp_port_; }
private:
    void sender_loop();
    const unsigned int client_id_;
    const std::string session_id_;
    const int control_fd_;
    const std::string client_ip_;
    const std::uint16_t client_rtp_port_, client_rtcp_port_;
    int rtcp_fd_;
    std::shared_ptr<RtpSink> sink_;
    FanoutFramePool& frames_;
    BoundedFrameQueue queue_;
    const unsigned int artificial_send_delay_ms_;
    mutable std::mutex state_mutex_;
    bool playing_ = false;
    std::atomic<bool> stopping_;
    std::thread sender_;
    RtspClientStats stats_;
};

} // namespace lp2
