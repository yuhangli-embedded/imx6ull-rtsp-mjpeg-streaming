#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <string>
#include <thread>

#include <linux/videodev2.h>

#include "lp2/bounded_frame_queue.hpp"
#include "lp2/fanout_frame_pool.hpp"
#include "lp2/jpeg_validator.hpp"
#include "lp2/pipeline_stats.hpp"
#include "lp2/rtsp_server.hpp"
#include "lp2/v4l2_capture.hpp"

namespace {
volatile std::sig_atomic_t interrupted = 0;
void on_signal(int) { interrupted = 1; }

struct Config {
    lp2::CaptureRequest capture;
    unsigned int frames = 0; // continuous until SIGINT/SIGTERM
    unsigned int rtsp_port = 8554;
    unsigned int max_clients = 2;
    unsigned int slow_client_id = 0;
    unsigned int slow_client_delay_ms = 0;
    unsigned int udp_gap_us = 10;
    unsigned int udp_frame_budget_ms = 100;
    std::string path = "/live";
};

bool number(const char* text, unsigned int& result, bool zero_ok)
{
    if (!text || !*text || *text == '-') return false;
    char* end = nullptr;
    errno = 0;
    const unsigned long value = std::strtoul(text, &end, 10);
    if (errno || end == text || *end || (!zero_ok && value == 0) ||
        value > std::numeric_limits<unsigned int>::max()) return false;
    result = static_cast<unsigned int>(value);
    return true;
}

void usage(const char* name)
{
    std::cout << "Usage: " << name << " [options]\n"
              << "  --device PATH                 /dev/video2\n"
              << "  --width N --height N --fps N   1280x720 @30 MJPEG\n"
              << "  --rtsp-port N                 8554\n"
              << "  --max-clients N               1 or 2 (default: 2)\n"
              << "  --slow-client-id N            0, 1 or 2; 0 disables (default: 0)\n"
              << "  --slow-client-delay-ms N      sender-only 0..1000 ms (default: 0)\n"
              << "  --path PATH                   /live (track is PATH/track1)\n"
              << "  --udp-gap-us N                10\n"
              << "  --udp-frame-budget-ms N       100\n"
              << "  --frames N                    0 means continuous (default)\n"
              << "  --help\n";
}

bool arguments(int argc, char** argv, Config& config)
{
    for (int i = 1; i < argc; ++i) {
        const std::string option = argv[i];
        if (option == "--help") { usage(argv[0]); std::exit(0); }
        if (++i >= argc) return false;
        const char* value = argv[i];
        if (option == "--device") config.capture.device = value;
        else if (option == "--path") config.path = value;
        else {
            unsigned int parsed = 0;
            const bool zero_ok = option == "--frames" || option == "--udp-gap-us" ||
                option == "--slow-client-id" || option == "--slow-client-delay-ms";
            if (!number(value, parsed, zero_ok)) return false;
            if (option == "--width") config.capture.width = parsed;
            else if (option == "--height") config.capture.height = parsed;
            else if (option == "--fps") config.capture.fps = parsed;
            else if (option == "--frames") config.frames = parsed;
            else if (option == "--rtsp-port") config.rtsp_port = parsed;
            else if (option == "--max-clients") config.max_clients = parsed;
            else if (option == "--slow-client-id") config.slow_client_id = parsed;
            else if (option == "--slow-client-delay-ms")
                config.slow_client_delay_ms = parsed;
            else if (option == "--udp-gap-us") config.udp_gap_us = parsed;
            else if (option == "--udp-frame-budget-ms") config.udp_frame_budget_ms = parsed;
            else return false;
        }
    }
    return !config.capture.device.empty() && config.rtsp_port <= 65535 &&
        config.max_clients >= 1 && config.max_clients <= 2 &&
        config.slow_client_id <= config.max_clients &&
        (config.slow_client_id != 0 || config.slow_client_delay_ms == 0) &&
        config.slow_client_delay_ms <= 1000 &&
        config.path.size() > 1 && config.path[0] == '/' &&
        config.path[config.path.size() - 1] != '/' &&
        config.path.find('?') == std::string::npos &&
        config.path.find('#') == std::string::npos &&
        config.path.find(' ') == std::string::npos;
}

std::string fourcc(std::uint32_t value)
{
    std::string result(4, ' ');
    for (unsigned int i = 0; i < 4; ++i)
        result[i] = static_cast<char>((value >> (i * 8)) & 0xff);
    return result;
}

double milliseconds(std::chrono::steady_clock::duration duration)
{
    return std::chrono::duration_cast<
        std::chrono::duration<double, std::milli> >(duration).count();
}

double fps(std::uint64_t count,
           std::chrono::steady_clock::time_point first,
           std::chrono::steady_clock::time_point last)
{
    const double seconds = milliseconds(last - first) / 1000.0;
    return count > 1 && seconds > 0 ? (count - 1) / seconds : 0.0;
}
}

int main(int argc, char** argv)
{
    Config config;
    if (!arguments(argc, argv, config)) { usage(argv[0]); return 2; }
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    lp2::V4L2Capture capture;
    if (!capture.open_and_configure(config.capture)) {
        std::cerr << "Capture setup: " << capture.error() << '\n';
        return 1;
    }
    const lp2::CaptureFormat format = capture.format();
    lp2::FanoutFramePool pool(format.size_image);
    lp2::BoundedFrameQueue queue(4);
    lp2::PipelineStats capture_stats, consumer_stats;
    std::uint64_t input_valid = 0, input_invalid = 0, integrity_dropped = 0;
    std::uint64_t missing_soi = 0, missing_eoi = 0, no_play_frames = 0;
    std::uint64_t delivered_to_rtp_sink = 0;
    std::atomic<bool> stop_requested(false);
    std::mutex start_mutex;
    std::condition_variable start_cv;
    bool first_play = false;
    std::string capture_error;
    bool server_ok = false;
    lp2::RtspServer server(static_cast<std::uint16_t>(config.rtsp_port),
        config.path, config.max_clients, config.udp_gap_us,
        config.udp_frame_budget_ms, config.slow_client_id,
        config.slow_client_delay_ms, pool, stop_requested, interrupted, [&] {
            std::lock_guard<std::mutex> lock(start_mutex);
            first_play = true;
            start_cv.notify_all();
        });

    std::cout << "===== LP2 M5 RTSP/JPEG =====\n"
              << "Device: " << config.capture.device << '\n'
              << "Width: " << format.width << "\nHeight: " << format.height
              << "\nPixel format: " << fourcc(format.pixel_format)
              << "\nConfigured FPS: " << format.configured_fps
              << "\nFramePool: 6\nCapture queue: 4 (drop oldest)\n"
              << "Sender queue per client: 2 (drop oldest)\n"
              << "Max clients: " << config.max_clients << '\n'
              << "Slow client ID/delay ms: " << config.slow_client_id << '/'
              << config.slow_client_delay_ms << '\n'
              << "RTSP: rtsp://<board-ip>:" << config.rtsp_port << config.path
              << "\nRTP/JPEG payload type: 26\nRTP server port pairs: 5004-5005, 5006-5007"
              << "\nUDP gap: " << config.udp_gap_us << " us"
              << "\nUDP frame budget: " << config.udp_frame_budget_ms << " ms"
              << "\nTarget captured frames: " << config.frames
              << " (0 = continuous)\n" << std::flush;

    std::thread consumer([&] {
        lp2::Frame* frame = nullptr;
        while (queue.pop(frame)) {
            const auto now = std::chrono::steady_clock::now();
            if (!consumer_stats.have_consume_time) {
                consumer_stats.first_consume_time = now;
                consumer_stats.have_consume_time = true;
            }
            consumer_stats.last_consume_time = now;
            const double age = milliseconds(now - frame->application_capture_time);
            consumer_stats.queue_age_sum_ms += age;
            if (age > consumer_stats.queue_age_max_ms)
                consumer_stats.queue_age_max_ms = age;
            const bool metadata_ok = frame->size <= frame->storage.size() &&
                frame->width == format.width && frame->height == format.height &&
                frame->pixel_format == format.pixel_format;
            bool valid = false;
            if (!metadata_ok) {
                ++consumer_stats.invalid_consumer_frames;
                stop_requested.store(true);
                start_cv.notify_all();
            } else {
                const lp2::JpegValidationResult check =
                    lp2::JpegValidator::validate(*frame);
                if (!check.valid) {
                    ++input_invalid;
                    ++integrity_dropped;
                    if (check.missing_soi) ++missing_soi;
                    if (check.missing_eoi) ++missing_eoi;
                } else {
                    ++input_valid;
                    valid = true;
                }
            }
            // After fan-out a sender may return this slot to FramePool at any
            // moment. Complete all reads of Frame metadata before transfer.
            const double latency = milliseconds(
                std::chrono::steady_clock::now() - frame->application_capture_time);
            consumer_stats.latency_sum_ms += latency;
            if (latency > consumer_stats.latency_max_ms)
                consumer_stats.latency_max_ms = latency;
            ++consumer_stats.consumed_frames;
            consumer_stats.consumed_bytes += frame->size;
            if (valid) {
                const std::size_t offered = server.offer_valid(frame);
                delivered_to_rtp_sink += offered;
                if (offered == 0) ++no_play_frames;
            } else {
                pool.release_unshared(frame);
            }
            frame = nullptr;
        }
    });

    std::thread control([&] {
        server_ok = server.run();
        stop_requested.store(true);
        start_cv.notify_all();
    });

    std::thread producer([&] {
        {
            std::unique_lock<std::mutex> lock(start_mutex);
            while (!first_play && !stop_requested.load() && !interrupted)
                start_cv.wait_for(lock, std::chrono::milliseconds(100));
        }
        if (stop_requested.load() || interrupted) { queue.close(); return; }
        if (!capture.start()) {
            capture_error = capture.error();
            stop_requested.store(true);
            queue.close(); return;
        }
        const double cadence = format.configured_fps > 0 ?
            format.configured_fps : config.capture.fps;
        while (!stop_requested.load() && !interrupted &&
               (config.frames == 0 || capture_stats.captured_frames < config.frames)) {
            lp2::CapturedBuffer source;
            const lp2::DequeueResult result = capture.dequeue(source, 2000);
            if (result == lp2::DequeueResult::Timeout) {
                ++capture_stats.timeouts; continue;
            }
            if (result == lp2::DequeueResult::Again) continue;
            if (result == lp2::DequeueResult::Error) {
                capture_error = capture.error(); stop_requested.store(true); break;
            }
            const auto now = std::chrono::steady_clock::now();
            if (!capture_stats.have_capture_time) {
                capture_stats.first_capture_time = now;
                capture_stats.have_capture_time = true;
            } else {
                const double interval = milliseconds(now - capture_stats.previous_capture_time);
                if (interval > capture_stats.max_dequeue_interval_ms)
                    capture_stats.max_dequeue_interval_ms = interval;
                if (interval > 1500.0 / cadence)
                    ++capture_stats.long_dequeue_intervals;
            }
            capture_stats.previous_capture_time = now;
            capture_stats.last_capture_time = now;
            ++capture_stats.captured_frames;
            if (source.flags & V4L2_BUF_FLAG_ERROR)
                ++capture_stats.v4l2_error_frames;
            if (capture_stats.have_previous_sequence) {
                const std::uint32_t delta = source.sequence - capture_stats.previous_sequence;
                if (delta == 0) ++capture_stats.duplicate_sequences;
                else if (delta < 0x80000000U) {
                    if (delta > 1) {
                        ++capture_stats.sequence_gap_events;
                        capture_stats.driver_reported_drops += delta - 1;
                    }
                } else ++capture_stats.backward_sequences;
            }
            capture_stats.previous_sequence = source.sequence;
            capture_stats.have_previous_sequence = true;
            lp2::Frame* frame = pool.acquire_capture();
            if (!frame) {
                ++capture_stats.pool_exhaustion;
                lp2::Frame* oldest = queue.drop_oldest();
                if (oldest) {
                    ++capture_stats.queue_dropped_frames;
                    pool.release_unshared(oldest);
                    frame = pool.acquire_capture();
                }
            }
            if (!frame) {
                if (!capture.requeue(source.index)) {
                    capture_error = capture.error(); stop_requested.store(true); break;
                }
                continue;
            }
            if (source.size > frame->storage.size()) {
                pool.release_unshared(frame);
                capture_error = "bytesused exceeds FramePool buffer";
                capture.requeue(source.index);
                stop_requested.store(true); break;
            }
            std::memcpy(frame->storage.data(), source.data, source.size);
            frame->sequence = source.sequence;
            frame->capture_timestamp_us = source.capture_timestamp_us;
            frame->size = source.size;
            frame->width = format.width;
            frame->height = format.height;
            frame->pixel_format = format.pixel_format;
            frame->application_capture_time = now;
            capture_stats.copied_bytes += source.size;
            if (!capture.requeue(source.index)) {
                pool.release_unshared(frame);
                capture_error = capture.error(); stop_requested.store(true); break;
            }
            const double hold = milliseconds(std::chrono::steady_clock::now() - now);
            if (hold > capture_stats.max_v4l2_buffer_hold_ms)
                capture_stats.max_v4l2_buffer_hold_ms = hold;
            ++capture_stats.produced_frames;
            lp2::Frame* dropped = queue.push_drop_oldest(frame);
            if (dropped) {
                ++capture_stats.queue_dropped_frames;
                pool.release_unshared(dropped);
            }
        }
        capture.stop();
        if (!capture.error().empty()) {
            capture_error = capture.error(); stop_requested.store(true);
        }
        queue.close();
    });

    producer.join();
    consumer.join();
    stop_requested.store(true);
    control.join();
    const lp2::RtspStats& net = server.stats();
    const lp2::FanoutOwnershipStats ownership = pool.stats();
    const double capture_fps = capture_stats.have_capture_time ? fps(
        capture_stats.captured_frames, capture_stats.first_capture_time,
        capture_stats.last_capture_time) : 0;
    const double consumer_fps = consumer_stats.have_consume_time ? fps(
        consumer_stats.consumed_frames, consumer_stats.first_consume_time,
        consumer_stats.last_consume_time) : 0;
    std::cout << std::fixed << std::setprecision(3)
              << "===== LP2 M5 RTSP/JPEG Statistics =====\n"
              << "RTSP clients accepted: " << net.tcp_clients_accepted << '\n'
              << "RTSP clients disconnected: " << net.tcp_clients_disconnected << '\n'
              << "RTSP clients rejected: " << net.tcp_clients_rejected << '\n'
              << "RTSP OPTIONS/DESCRIBE/SETUP/PLAY/TEARDOWN: "
              << net.options_requests << '/' << net.describe_requests << '/'
              << net.setup_requests << '/' << net.play_requests << '/'
              << net.teardown_requests << '\n'
              << "RTSP sessions created: " << net.sessions_created << '\n'
              << "RTSP sessions released: " << net.sessions_released << '\n'
              << "Current active sessions: " << net.current_active_sessions << '\n'
              << "Peak active sessions: " << net.peak_active_sessions << '\n'
              << "Current open client sockets: "
              << net.current_open_client_sockets << '\n'
              << "RTP sink create count: " << net.rtp_sink_create_count << '\n'
              << "RTP sink destroy count: " << net.rtp_sink_destroy_count << '\n'
              << "Current/last client RTP port: "
              << net.current_client_rtp_port << '/' << net.last_client_rtp_port << '\n'
              << "Current client RTP ports: "
              << net.current_client_rtp_ports[0] << '/'
              << net.current_client_rtp_ports[1] << '\n'
              << "Current RTP sinks active: "
              << (net.rtp_sink_create_count - net.rtp_sink_destroy_count) << '\n'
              << "RTSP bad/unsupported requests: " << net.bad_requests << '/'
              << net.unsupported_requests << '\n'
              << "Captured frames: " << capture_stats.captured_frames << '\n'
              << "Produced frames: " << capture_stats.produced_frames << '\n'
              << "Consumer received frames: " << consumer_stats.consumed_frames << '\n'
              << "Input valid/invalid JPEG frames: " << input_valid << '/'
              << input_invalid << '\n'
              << "Integrity dropped frames: " << integrity_dropped << '\n'
              << "Missing SOI/EOI: " << missing_soi << '/' << missing_eoi << '\n'
              << "Valid frames without PLAY: " << no_play_frames << '\n'
              << "Sender queue frame offers accepted: "
              << delivered_to_rtp_sink << '\n'
              << "RTP-incompatible frames: " << net.rtp_incompatible_frames << '\n'
              << "RTP frames fully submitted to kernel: " << net.rtp_frames_submitted << '\n'
              << "RTP send-failed frames: " << net.rtp_send_failures << '\n'
              << "RTP budget-expired frames: " << net.rtp_budget_failures << '\n'
              << "RTP datagrams submitted to kernel: " << net.rtp_packets_sent << '\n'
              << "RTP bytes submitted to kernel: " << net.rtp_bytes_sent << '\n'
              << "Capture queue dropped frames: "
              << capture_stats.queue_dropped_frames << '\n'
              << "Pool exhaustion: " << capture_stats.pool_exhaustion << '\n'
              << "Max/current queue depth: " << queue.max_depth() << '/'
              << queue.current_depth() << '\n'
              << "Pool available at exit: " << pool.available() << '/'
              << pool.capacity() << '\n'
              << "Capture/consumer FPS: " << capture_fps << '/'
              << consumer_fps << '\n'
              << "Average/max queue age ms: "
              << (consumer_stats.consumed_frames ?
                  consumer_stats.queue_age_sum_ms / consumer_stats.consumed_frames : 0)
              << '/' << consumer_stats.queue_age_max_ms << '\n'
              << "Average/max capture-to-fanout dispatch ms: "
              << (consumer_stats.consumed_frames ?
                  consumer_stats.latency_sum_ms / consumer_stats.consumed_frames : 0)
              << '/' << consumer_stats.latency_max_ms << '\n'
              << "Max V4L2 buffer hold ms: " << capture_stats.max_v4l2_buffer_hold_ms
              << "\nV4L2 error frames: " << capture_stats.v4l2_error_frames
              << "\nTimeouts: " << capture_stats.timeouts
              << "\nSequence gap events: " << capture_stats.sequence_gap_events
              << "\nDriver-reported sequence drops: " << capture_stats.driver_reported_drops
              << "\nFrame refcount acquire operations: " << ownership.ref_acquires
              << "\nFrame refcount release operations: " << ownership.ref_releases
              << "\nFrame capture acquires: " << ownership.capture_acquires
              << "\nFrames returned to pool: " << ownership.frames_returned
              << "\nFrame ownership errors: " << ownership.ownership_errors
              << "\nReference milestone: M5.3B CLOSED; this run requires separate Gate review\n";
    for (unsigned int i = 0; i < config.max_clients; ++i) {
        const lp2::RtspClientStats& client = net.client_totals[i];
        std::cout << "Client ID: " << i + 1 << '\n'
                  << "  Artificial delay enabled: "
                  << (client.artificial_send_delay_ms ? "yes" : "no") << '\n'
                  << "  Artificial delay ms: "
                  << client.artificial_send_delay_ms << '\n'
                  << "  PLAY frames offered: " << client.play_frames_offered << '\n'
                  << "  Sender queue enqueued: " << client.sender_queue_enqueued << '\n'
                  << "  Sender queue dropped: " << client.sender_queue_dropped << '\n'
                  << "  Frames dequeued by sender: "
                  << client.frames_dequeued_by_sender << '\n'
                  << "  RTP frames submitted: " << client.rtp_frames_submitted << '\n'
                  << "  RTP packets sent: " << client.rtp_packets_sent << '\n'
                  << "  RTP bytes sent: " << client.rtp_bytes_sent << '\n'
                  << "  RTP send failures: " << client.rtp_send_failures << '\n'
                  << "  Budget-expired frames: " << client.budget_expired_frames << '\n'
                  << "  Current/max sender queue depth: "
                  << client.current_sender_queue_depth << '/'
                  << client.max_sender_queue_depth << '\n';
    }
    if (!capture_error.empty()) std::cerr << "Capture error: " << capture_error << '\n';
    if (!server.error().empty()) std::cerr << "RTSP error: " << server.error() << '\n';
    std::uint64_t sender_enqueued = 0;
    bool sender_queues_empty = true;
    for (unsigned int i = 0; i < config.max_clients; ++i) {
        sender_enqueued += net.client_totals[i].sender_queue_enqueued;
        sender_queues_empty = sender_queues_empty &&
            net.client_totals[i].current_sender_queue_depth == 0;
    }
    const bool accounting = capture_stats.produced_frames ==
        consumer_stats.consumed_frames + capture_stats.queue_dropped_frames &&
        input_valid + integrity_dropped == consumer_stats.consumed_frames &&
        input_invalid == integrity_dropped &&
        sender_enqueued == delivered_to_rtp_sink && sender_queues_empty &&
        pool.available() == pool.capacity() && queue.current_depth() == 0 &&
        ownership.capture_acquires == ownership.frames_returned &&
        ownership.ref_acquires == ownership.ref_releases &&
        ownership.ownership_errors == 0;
    const bool rtsp_resources_released =
        net.tcp_clients_accepted == net.tcp_clients_disconnected &&
        net.sessions_created == net.sessions_released &&
        net.current_active_sessions == 0 &&
        net.peak_active_sessions <= config.max_clients &&
        net.rtp_sink_create_count == net.rtp_sink_destroy_count &&
        net.current_open_client_sockets == 0;
    return server_ok && capture_error.empty() && accounting &&
        rtsp_resources_released &&
        consumer_stats.invalid_consumer_frames == 0 ? 0 : 1;
}
