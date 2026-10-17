#include "lp2/rtsp_server.hpp"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <exception>
#include <iostream>
#include <sstream>
#include <utility>
#include <vector>

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace lp2 {
namespace {
typedef std::vector<std::pair<std::string, std::string> > Headers;

std::string decimal(unsigned long value)
{
    std::ostringstream out; out << value; return out.str();
}
std::string address_of(const struct sockaddr_in& address)
{
    char text[INET_ADDRSTRLEN] = {};
    return inet_ntop(AF_INET, &address.sin_addr, text, sizeof(text))
        ? text : std::string();
}
bool nonblocking(int fd)
{
    const int flags = fcntl(fd, F_GETFL, 0);
    return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}
void add_client_stats(RtspClientStats& total, const RtspClientStats& one)
{
    total.artificial_send_delay_ms = one.artificial_send_delay_ms;
    total.play_frames_offered += one.play_frames_offered;
    total.sender_queue_enqueued += one.sender_queue_enqueued;
    total.sender_queue_dropped += one.sender_queue_dropped;
    total.frames_dequeued_by_sender += one.frames_dequeued_by_sender;
    total.rtp_frames_submitted += one.rtp_frames_submitted;
    total.rtp_packets_sent += one.rtp_packets_sent;
    total.rtp_bytes_sent += one.rtp_bytes_sent;
    total.rtp_send_failures += one.rtp_send_failures;
    total.budget_expired_frames += one.budget_expired_frames;
    total.rtp_incompatible_frames += one.rtp_incompatible_frames;
    total.current_sender_queue_depth = one.current_sender_queue_depth;
    if (one.max_sender_queue_depth > total.max_sender_queue_depth)
        total.max_sender_queue_depth = one.max_sender_queue_depth;
}
}

RtspServer::RtspServer(std::uint16_t rtsp_port, const std::string& path,
                       unsigned int max_clients, unsigned int gap_us,
                       unsigned int budget_ms, unsigned int slow_client_id,
                       unsigned int slow_client_delay_ms, FanoutFramePool& frames,
                       std::atomic<bool>& stop_requested,
                       volatile std::sig_atomic_t& interrupted,
                       const std::function<void()>& on_first_play)
    : rtsp_port_(rtsp_port), path_(path), max_clients_(max_clients),
      gap_us_(gap_us), budget_ms_(budget_ms),
      slow_client_id_(slow_client_id),
      slow_client_delay_ms_(slow_client_delay_ms), frames_(frames),
      stop_requested_(stop_requested), interrupted_(interrupted),
      on_first_play_(on_first_play), ever_played_(false)
{
    for (unsigned int i = 0; i < 2; ++i) control_done_[i].store(false);
}

RtspServer::~RtspServer()
{
    stop_requested_.store(true);
    for (unsigned int i = 0; i < 2; ++i)
        if (control_threads_[i].joinable()) control_threads_[i].join();
    for (unsigned int i = 0; i < 2; ++i) release_session(i);
    if (listen_fd_ >= 0) close(listen_fd_);
}

void RtspServer::log_line(const std::string& line)
{
    std::lock_guard<std::mutex> lock(log_mutex_);
    std::cout << line << std::endl;
}

bool RtspServer::stopped() const
{
    return stop_requested_.load() || interrupted_ != 0;
}

std::shared_ptr<RtspClientSession> RtspServer::session_for(unsigned int slot)
{
    std::lock_guard<std::mutex> lock(registry_mutex_);
    return sessions_[slot];
}

void RtspServer::release_session(unsigned int slot)
{
    std::shared_ptr<RtspClientSession> session;
    {
        std::lock_guard<std::mutex> lock(registry_mutex_);
        session.swap(sessions_[slot]);
    }
    if (!session) return;
    const std::string id = session->session_id();
    const RtspClientStats one = session->stop_and_join();
    {
        std::lock_guard<std::mutex> lock(stats_mutex_);
        add_client_stats(stats_.client_totals[slot], one);
        stats_.rtp_frames_submitted += one.rtp_frames_submitted;
        stats_.rtp_packets_sent += one.rtp_packets_sent;
        stats_.rtp_bytes_sent += one.rtp_bytes_sent;
        stats_.rtp_send_failures += one.rtp_send_failures;
        stats_.rtp_budget_failures += one.budget_expired_frames;
        stats_.rtp_incompatible_frames += one.rtp_incompatible_frames;
        ++stats_.sessions_released;
        --stats_.current_active_sessions;
        stats_.current_client_rtp_ports[slot] = 0;
        stats_.current_client_rtp_port = stats_.current_client_rtp_ports[0]
            ? stats_.current_client_rtp_ports[0]
            : stats_.current_client_rtp_ports[1];
    }
    log_line("RTSP session released: " + id + " client=" + decimal(slot + 1));
}

std::size_t RtspServer::offer_valid(Frame* frame)
{
    std::array<std::shared_ptr<RtspClientSession>, 2> targets;
    {
        std::lock_guard<std::mutex> lock(registry_mutex_);
        targets = sessions_;
    }
    std::array<bool, 2> active = {{false, false}};
    unsigned int owners = 0;
    for (unsigned int i = 0; i < max_clients_; ++i) {
        active[i] = targets[i] && targets[i]->is_playing();
        if (active[i]) ++owners;
    }
    if (owners == 0) {
        frames_.release_unshared(frame);
        return 0;
    }
    if (!frames_.grant(frame, owners)) {
        frames_.release_unshared(frame);
        return 0;
    }
    std::size_t offered = 0;
    for (unsigned int i = 0; i < max_clients_; ++i) {
        if (!active[i]) continue;
        Frame* dropped = nullptr;
        if (targets[i]->offer(frame, dropped)) ++offered;
        else frames_.release_ref(frame); // session stopped after snapshot
        if (dropped) frames_.release_ref(dropped);
    }
    return offered;
}

bool RtspServer::send_all(int fd, const std::string& bytes)
{
    const std::chrono::steady_clock::time_point deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(2);
    std::size_t sent = 0;
    while (sent < bytes.size() && !stopped() &&
           std::chrono::steady_clock::now() < deadline) {
        const ssize_t count = send(fd, bytes.data() + sent,
                                   bytes.size() - sent, MSG_NOSIGNAL);
        if (count > 0) { sent += static_cast<std::size_t>(count); continue; }
        if (count < 0 && errno == EINTR) continue;
        if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            struct pollfd waitfd {}; waitfd.fd = fd; waitfd.events = POLLOUT;
            if (poll(&waitfd, 1, 100) >= 0) continue;
            if (errno == EINTR) continue;
        }
        return false;
    }
    return sent == bytes.size();
}

RtspServer::Reply RtspServer::handle_request(
    unsigned int slot, int fd, const rtsp::Request& request,
    const std::string& peer_ip, const std::string& board_ip)
{
    Reply reply;
    const bool aggregate = request.path == path_ || request.path == path_ + "/";
    const bool track = request.path == path_ + "/track1";
    if (!aggregate && !track && !(request.method == "OPTIONS" &&
                                  request.path == "*")) {
        reply.bytes = rtsp::response(404, "Not Found", request.cseq, Headers());
        return reply;
    }
    if (request.method == "OPTIONS") {
        std::lock_guard<std::mutex> lock(stats_mutex_);
        ++stats_.options_requests;
        Headers headers;
        headers.push_back(std::make_pair("Public",
            "OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN"));
        reply.bytes = rtsp::response(200, "OK", request.cseq, headers);
    } else if (request.method == "DESCRIBE") {
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.describe_requests;
        }
        if (!aggregate) {
            reply.bytes = rtsp::response(404, "Not Found", request.cseq, Headers());
            return reply;
        }
        log_line("RTSP DESCRIBE client=" + decimal(slot + 1));
        const std::string base = "rtsp://" + board_ip + ":" +
            decimal(rtsp_port_) + path_ + "/";
        Headers headers;
        headers.push_back(std::make_pair("Content-Type", "application/sdp"));
        headers.push_back(std::make_pair("Content-Base", base));
        reply.bytes = rtsp::response(200, "OK", request.cseq, headers,
                                     rtsp::sdp(board_ip));
    } else if (request.method == "SETUP") {
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.setup_requests;
        }
        if (!track) {
            reply.bytes = rtsp::response(404, "Not Found", request.cseq, Headers());
            return reply;
        }
        if (session_for(slot)) {
            reply.bytes = rtsp::response(455, "Method Not Valid in This State",
                                         request.cseq, Headers());
            return reply;
        }
        std::uint16_t client_rtp = 0, client_rtcp = 0;
        if (!rtsp::parse_client_ports(rtsp::header(request, "transport"),
                                      client_rtp, client_rtcp)) {
            {
                std::lock_guard<std::mutex> lock(stats_mutex_);
                ++stats_.bad_requests;
            }
            reply.bytes = rtsp::response(461, "Unsupported Transport",
                                         request.cseq, Headers());
            return reply;
        }
        const std::uint16_t server_rtp = static_cast<std::uint16_t>(5004 + 2 * slot);
        const std::uint16_t server_rtcp = server_rtp + 1;
        std::shared_ptr<RtpSink> candidate(new RtpSink(
            peer_ip, client_rtp, gap_us_, budget_ms_, 26, server_rtp),
            [this](RtpSink* sink) {
                delete sink;
                std::lock_guard<std::mutex> lock(stats_mutex_);
                ++stats_.rtp_sink_destroy_count;
            });
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.rtp_sink_create_count;
        }
        if (!candidate->initialize()) {
            log_line("RTSP SETUP rejected: " + candidate->error());
            reply.bytes = rtsp::response(500, "Internal Server Error",
                                         request.cseq, Headers());
            return reply;
        }
        int rtcp_fd = socket(AF_INET, SOCK_DGRAM, 0);
        struct sockaddr_in rtcp_addr {};
        rtcp_addr.sin_family = AF_INET;
        rtcp_addr.sin_addr.s_addr = htonl(INADDR_ANY);
        rtcp_addr.sin_port = htons(server_rtcp);
        if (rtcp_fd < 0 || bind(rtcp_fd,
            reinterpret_cast<const struct sockaddr*>(&rtcp_addr),
            sizeof(rtcp_addr)) < 0) {
            log_line(std::string("RTSP RTCP reservation rejected: ") +
                     std::strerror(errno));
            if (rtcp_fd >= 0) close(rtcp_fd);
            reply.bytes = rtsp::response(500, "Internal Server Error",
                                         request.cseq, Headers());
            return reply;
        }
        std::uint64_t ordinal = 0;
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ordinal = stats_.sessions_created;
        }
        const std::uint64_t ticks = static_cast<std::uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count());
        std::ostringstream id;
        id << std::hex << (ticks ^ static_cast<std::uint64_t>(getpid()) ^
                           (ordinal << 2) ^ slot);
        std::shared_ptr<RtspClientSession> session(new RtspClientSession(
            slot + 1, id.str(), fd, peer_ip, client_rtp, client_rtcp,
            rtcp_fd, candidate, frames_,
            slow_client_id_ == slot + 1 ? slow_client_delay_ms_ : 0));
        if (!session->start_sender()) {
            log_line("RTSP SETUP rejected: sender thread unavailable");
            reply.bytes = rtsp::response(500, "Internal Server Error",
                                         request.cseq, Headers());
            return reply;
        }
        {
            std::lock_guard<std::mutex> lock(registry_mutex_);
            sessions_[slot] = session;
        }
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.sessions_created;
            ++stats_.current_active_sessions;
            if (stats_.current_active_sessions > stats_.peak_active_sessions)
                stats_.peak_active_sessions = stats_.current_active_sessions;
            stats_.current_client_rtp_port = client_rtp;
            stats_.last_client_rtp_port = client_rtp;
            stats_.current_client_rtp_ports[slot] = client_rtp;
        }
        log_line("RTSP SETUP client=" + decimal(slot + 1) +
                 " client_rtp_port=" + decimal(client_rtp));
        Headers headers;
        headers.push_back(std::make_pair("Session", id.str()));
        headers.push_back(std::make_pair("Transport",
            "RTP/AVP;unicast;client_port=" + decimal(client_rtp) + "-" +
            decimal(client_rtcp) + ";server_port=" + decimal(server_rtp) +
            "-" + decimal(server_rtcp) + ";source=" + board_ip));
        reply.bytes = rtsp::response(200, "OK", request.cseq, headers);
    } else if (request.method == "PLAY") {
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.play_requests;
        }
        const std::shared_ptr<RtspClientSession> session = session_for(slot);
        if (!session || rtsp::session_token(rtsp::header(request, "session")) !=
                        session->session_id()) {
            reply.bytes = rtsp::response(454, "Session Not Found",
                                         request.cseq, Headers());
            return reply;
        }
        Headers headers;
        headers.push_back(std::make_pair("Session", session->session_id()));
        reply.bytes = rtsp::response(200, "OK", request.cseq, headers);
        reply.activate_after_send = true;
    } else if (request.method == "TEARDOWN") {
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.teardown_requests;
        }
        const std::shared_ptr<RtspClientSession> session = session_for(slot);
        if (!session || rtsp::session_token(rtsp::header(request, "session")) !=
                        session->session_id()) {
            reply.bytes = rtsp::response(454, "Session Not Found",
                                         request.cseq, Headers());
            return reply;
        }
        const std::string old_id = session->session_id();
        log_line("RTSP TEARDOWN session=" + old_id);
        release_session(slot);
        Headers headers;
        headers.push_back(std::make_pair("Session", old_id));
        reply.bytes = rtsp::response(200, "OK", request.cseq, headers);
    } else {
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.unsupported_requests;
        }
        reply.bytes = rtsp::response(501, "Not Implemented", request.cseq,
                                     Headers());
    }
    return reply;
}

void RtspServer::handle_client(unsigned int slot, int fd,
                                const std::string& peer_ip,
                                const std::string& board_ip)
{
    std::string input;
    while (!stopped()) {
        struct pollfd waitfd {}; waitfd.fd = fd; waitfd.events = POLLIN;
        const int ready = poll(&waitfd, 1, 100);
        if (ready < 0) {
            if (errno == EINTR) continue;
            log_line(std::string("RTSP TCP poll error: ") + std::strerror(errno));
            return;
        }
        if (ready == 0) continue;
        if (waitfd.revents & (POLLERR | POLLNVAL)) {
            log_line("RTSP TCP poll error"); return;
        }
        char bytes[2048];
        const ssize_t count = recv(fd, bytes, sizeof(bytes), 0);
        if (count == 0) { log_line("RTSP TCP EOF"); return; }
        if (count < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
                continue;
            log_line(std::string("RTSP TCP read error: ") + std::strerror(errno));
            return;
        }
        input.append(bytes, static_cast<std::size_t>(count));
        for (;;) {
            rtsp::Request request;
            std::size_t used = 0; std::string parse_error;
            const rtsp::ParseResult parsed = rtsp::parse_request(
                input, request, used, parse_error);
            if (parsed == rtsp::ParseResult::NeedMore) break;
            if (parsed == rtsp::ParseResult::Invalid) {
                {
                    std::lock_guard<std::mutex> lock(stats_mutex_);
                    ++stats_.bad_requests;
                }
                send_all(fd, rtsp::response(400, "Bad Request", request.cseq,
                                             Headers()));
                return;
            }
            input.erase(0, used);
            Reply reply = handle_request(slot, fd, request, peer_ip, board_ip);
            if (!send_all(fd, reply.bytes)) return;
            if (reply.activate_after_send) {
                const std::shared_ptr<RtspClientSession> session = session_for(slot);
                if (session) {
                    session->set_playing(true);
                    log_line("RTSP PLAY session=" + session->session_id());
                    if (!ever_played_.exchange(true)) on_first_play_();
                }
            }
        }
    }
}

void RtspServer::control_loop(unsigned int slot, int fd, std::string peer_ip,
                               std::uint16_t peer_port, std::string board_ip)
{
    log_line("RTSP client connected: " + peer_ip + ":" + decimal(peer_port) +
             " client=" + decimal(slot + 1));
    try { handle_client(slot, fd, peer_ip, board_ip); }
    catch (const std::exception& ex) {
        log_line(std::string("RTSP control error: ") + ex.what());
    }
    release_session(slot);
    close(fd);
    {
        std::lock_guard<std::mutex> lock(stats_mutex_);
        ++stats_.tcp_clients_disconnected;
        --stats_.current_open_client_sockets;
    }
    log_line("RTSP client disconnected: " + peer_ip +
             " client=" + decimal(slot + 1));
    control_done_[slot].store(true);
}

void RtspServer::reject_excess_client(int fd, const std::string& peer_ip,
                                      std::uint16_t peer_port)
{
    log_line("RTSP client rejected (max clients): " + peer_ip + ":" +
             decimal(peer_port));
    nonblocking(fd);
    std::string input;
    std::string cseq = "0";
    const std::chrono::steady_clock::time_point deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(1);
    while (!stopped() && std::chrono::steady_clock::now() < deadline) {
        struct pollfd waitfd {}; waitfd.fd = fd; waitfd.events = POLLIN;
        const int ready = poll(&waitfd, 1, 100);
        if (ready < 0) { if (errno == EINTR) continue; break; }
        if (ready == 0) continue;
        char bytes[2048];
        const ssize_t count = recv(fd, bytes, sizeof(bytes), 0);
        if (count <= 0) break;
        input.append(bytes, static_cast<std::size_t>(count));
        rtsp::Request request;
        std::size_t used = 0; std::string reason;
        const rtsp::ParseResult parsed = rtsp::parse_request(
            input, request, used, reason);
        if (parsed == rtsp::ParseResult::Complete) {
            cseq = request.cseq; break;
        }
        if (parsed == rtsp::ParseResult::Invalid) break;
    }
    send_all(fd, rtsp::response(453, "Not Enough Bandwidth", cseq, Headers()));
    close(fd);
}

void RtspServer::reap_completed()
{
    for (unsigned int i = 0; i < max_clients_; ++i) {
        if (control_done_[i].load() && control_threads_[i].joinable()) {
            control_threads_[i].join();
            control_done_[i].store(false);
        }
    }
}

bool RtspServer::run()
{
    listen_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) { error_ = std::strerror(errno); return false; }
    const int reuse = 1;
    setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    struct sockaddr_in listen_addr {};
    listen_addr.sin_family = AF_INET;
    listen_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    listen_addr.sin_port = htons(rtsp_port_);
    if (bind(listen_fd_, reinterpret_cast<const struct sockaddr*>(&listen_addr),
             sizeof(listen_addr)) < 0 ||
        listen(listen_fd_, 2) < 0 || !nonblocking(listen_fd_)) {
        error_ = std::string("RTSP listen setup: ") + std::strerror(errno);
        close(listen_fd_); listen_fd_ = -1;
        return false;
    }
    log_line("RTSP listening on TCP port " + decimal(rtsp_port_));
    while (!stopped()) {
        reap_completed();
        struct pollfd waitfd {}; waitfd.fd = listen_fd_; waitfd.events = POLLIN;
        const int ready = poll(&waitfd, 1, 100);
        if (ready < 0) {
            if (errno == EINTR) continue;
            error_ = std::string("RTSP accept poll: ") + std::strerror(errno);
            break;
        }
        if (ready == 0) continue;
        if (waitfd.revents & (POLLERR | POLLNVAL)) {
            error_ = "RTSP listening socket error"; break;
        }
        struct sockaddr_in peer {};
        socklen_t peer_len = sizeof(peer);
        const int fd = accept(listen_fd_,
            reinterpret_cast<struct sockaddr*>(&peer), &peer_len);
        if (fd < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            error_ = std::string("RTSP accept: ") + std::strerror(errno);
            break;
        }
        const std::string peer_ip = address_of(peer);
        const std::uint16_t peer_port = ntohs(peer.sin_port);
        reap_completed();
        int slot = -1;
        for (unsigned int i = 0; i < max_clients_; ++i) {
            if (!control_threads_[i].joinable()) { slot = static_cast<int>(i); break; }
        }
        if (slot < 0) {
            {
                std::lock_guard<std::mutex> lock(stats_mutex_);
                ++stats_.tcp_clients_rejected;
            }
            reject_excess_client(fd, peer_ip, peer_port);
            continue;
        }
        struct sockaddr_in local {};
        socklen_t local_len = sizeof(local);
        if (!nonblocking(fd) ||
            getsockname(fd, reinterpret_cast<struct sockaddr*>(&local),
                        &local_len) < 0 || address_of(local).empty()) {
            close(fd);
            continue;
        }
        {
            std::lock_guard<std::mutex> lock(stats_mutex_);
            ++stats_.tcp_clients_accepted;
            ++stats_.current_open_client_sockets;
        }
        control_done_[slot].store(false);
        try {
            control_threads_[slot] = std::thread(&RtspServer::control_loop,
                this, static_cast<unsigned int>(slot), fd, peer_ip, peer_port,
                address_of(local));
        } catch (const std::exception& ex) {
            error_ = std::string("RTSP control thread: ") + ex.what();
            close(fd);
            {
                std::lock_guard<std::mutex> lock(stats_mutex_);
                ++stats_.tcp_clients_disconnected;
                --stats_.current_open_client_sockets;
            }
            break;
        }
    }
    stop_requested_.store(true);
    for (unsigned int i = 0; i < max_clients_; ++i)
        if (control_threads_[i].joinable()) control_threads_[i].join();
    for (unsigned int i = 0; i < max_clients_; ++i) release_session(i);
    close(listen_fd_); listen_fd_ = -1;
    return error_.empty();
}

} // namespace lp2
