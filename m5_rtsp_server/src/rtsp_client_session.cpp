#include "lp2/rtsp_client_session.hpp"

#include <chrono>
#include <exception>
#include <unistd.h>

namespace lp2 {

RtspClientSession::RtspClientSession(
    unsigned int client_id, const std::string& session_id, int control_fd,
    const std::string& client_ip, std::uint16_t client_rtp_port,
    std::uint16_t client_rtcp_port, int rtcp_fd,
    std::shared_ptr<RtpSink> sink, FanoutFramePool& frames,
    unsigned int artificial_send_delay_ms)
    : client_id_(client_id), session_id_(session_id), control_fd_(control_fd),
      client_ip_(client_ip), client_rtp_port_(client_rtp_port),
      client_rtcp_port_(client_rtcp_port), rtcp_fd_(rtcp_fd),
      sink_(sink), frames_(frames), queue_(2),
      artificial_send_delay_ms_(artificial_send_delay_ms), stopping_(false)
{
    stats_.artificial_send_delay_ms = artificial_send_delay_ms_;
}

RtspClientSession::~RtspClientSession() { stop_and_join(); }

bool RtspClientSession::start_sender()
{
    try { sender_ = std::thread(&RtspClientSession::sender_loop, this); }
    catch (const std::exception&) { return false; }
    return true;
}

void RtspClientSession::set_playing(bool playing)
{
    std::lock_guard<std::mutex> lock(state_mutex_);
    if (!stopping_.load()) playing_ = playing;
}

bool RtspClientSession::is_playing() const
{
    std::lock_guard<std::mutex> lock(state_mutex_);
    return playing_ && !stopping_.load();
}

bool RtspClientSession::offer(Frame* frame, Frame*& dropped_oldest)
{
    dropped_oldest = nullptr;
    std::lock_guard<std::mutex> lock(state_mutex_);
    if (!playing_ || stopping_.load()) return false;
    ++stats_.play_frames_offered;
    dropped_oldest = queue_.push_drop_oldest(frame);
    ++stats_.sender_queue_enqueued;
    if (dropped_oldest) ++stats_.sender_queue_dropped;
    return true;
}

void RtspClientSession::sender_loop()
{
    Frame* frame = nullptr;
    while (queue_.pop(frame)) {
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            ++stats_.frames_dequeued_by_sender;
        }
        // Only this client's sender sleeps. No session, queue, or pool lock
        // is held, so the capture consumer and other sender keep running.
        if (!stopping_.load() && artificial_send_delay_ms_ != 0)
            std::this_thread::sleep_for(
                std::chrono::milliseconds(artificial_send_delay_ms_));
        if (!stopping_.load()) sink_->consume_prevalidated(*frame);
        frames_.release_ref(frame);
        frame = nullptr;
    }
}

RtspClientStats RtspClientSession::stop_and_join()
{
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        stopping_.store(true);
        playing_ = false;
        queue_.close();
    }
    if (sender_.joinable()) sender_.join();
    RtspClientStats result;
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        result = stats_;
    }
    result.current_sender_queue_depth = queue_.current_depth();
    result.max_sender_queue_depth = queue_.max_depth();
    if (sink_) {
        result.rtp_frames_submitted = sink_->fully_submitted_frames();
        result.rtp_packets_sent = sink_->submitted_datagrams();
        result.rtp_bytes_sent = sink_->submitted_bytes();
        result.rtp_send_failures = sink_->failed_frames();
        result.budget_expired_frames = sink_->budget_failures();
        result.rtp_incompatible_frames = sink_->incompatible_frames();
        sink_.reset();
    }
    if (rtcp_fd_ >= 0) { close(rtcp_fd_); rtcp_fd_ = -1; }
    return result;
}

} // namespace lp2
