#pragma once

#include <array>
#include <atomic>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "lp2/fanout_frame_pool.hpp"
#include "lp2/rtsp_client_session.hpp"
#include "lp2/rtsp_protocol.hpp"

namespace lp2 {

struct RtspStats {
    std::uint64_t tcp_clients_accepted = 0;
    std::uint64_t tcp_clients_disconnected = 0;
    std::uint64_t tcp_clients_rejected = 0;
    std::uint64_t options_requests = 0, describe_requests = 0,
                  setup_requests = 0, play_requests = 0,
                  teardown_requests = 0;
    std::uint64_t bad_requests = 0, unsupported_requests = 0,
                  sessions_created = 0, sessions_released = 0;
    std::uint64_t current_active_sessions = 0, peak_active_sessions = 0;
    std::uint64_t current_open_client_sockets = 0;
    std::uint64_t rtp_sink_create_count = 0, rtp_sink_destroy_count = 0;
    std::uint64_t rtp_frames_submitted = 0, rtp_packets_sent = 0,
                  rtp_bytes_sent = 0, rtp_send_failures = 0,
                  rtp_budget_failures = 0, rtp_incompatible_frames = 0;
    std::uint16_t current_client_rtp_port = 0;
    std::uint16_t last_client_rtp_port = 0;
    std::array<std::uint16_t, 2> current_client_rtp_ports = {{0, 0}};
    std::array<RtspClientStats, 2> client_totals;
};

class RtspServer {
public:
    RtspServer(std::uint16_t rtsp_port, const std::string& path,
               unsigned int max_clients, unsigned int gap_us,
               unsigned int budget_ms, unsigned int slow_client_id,
               unsigned int slow_client_delay_ms, FanoutFramePool& frames,
               std::atomic<bool>& stop_requested,
               volatile std::sig_atomic_t& interrupted,
               const std::function<void()>& on_first_play);
    ~RtspServer();
    bool run();
    // Takes ownership of a valid, unshared Frame. Never performs network I/O.
    std::size_t offer_valid(Frame* frame);
    const RtspStats& stats() const { return stats_; } // only after run joins
    const std::string& error() const { return error_; }
private:
    struct Reply {
        std::string bytes;
        bool activate_after_send = false;
    };
    void control_loop(unsigned int slot, int fd, std::string peer_ip,
                      std::uint16_t peer_port, std::string board_ip);
    void handle_client(unsigned int slot, int fd,
                       const std::string& peer_ip,
                       const std::string& board_ip);
    Reply handle_request(unsigned int slot, int fd,
                         const rtsp::Request& request,
                         const std::string& peer_ip,
                         const std::string& board_ip);
    void reject_excess_client(int fd, const std::string& peer_ip,
                              std::uint16_t peer_port);
    void reap_completed();
    std::shared_ptr<RtspClientSession> session_for(unsigned int slot);
    void release_session(unsigned int slot);
    bool send_all(int fd, const std::string& bytes);
    bool stopped() const;
    void log_line(const std::string& line);
    std::uint16_t rtsp_port_;
    std::string path_;
    unsigned int max_clients_, gap_us_, budget_ms_;
    unsigned int slow_client_id_, slow_client_delay_ms_;
    FanoutFramePool& frames_;
    std::atomic<bool>& stop_requested_;
    volatile std::sig_atomic_t& interrupted_;
    std::function<void()> on_first_play_;
    int listen_fd_ = -1;
    std::atomic<bool> ever_played_;
    std::array<std::thread, 2> control_threads_;
    std::array<std::atomic<bool>, 2> control_done_;
    std::array<std::shared_ptr<RtspClientSession>, 2> sessions_;
    std::mutex registry_mutex_, stats_mutex_, log_mutex_;
    RtspStats stats_;
    std::string error_;
};

} // namespace lp2
