#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>

namespace lp2 {

struct PipelineStats {
    std::uint64_t captured_frames = 0;
    std::uint64_t produced_frames = 0;
    std::uint64_t consumed_frames = 0;
    std::uint64_t queue_dropped_frames = 0;
    std::uint64_t pool_exhaustion = 0;
    std::uint64_t copied_bytes = 0;
    std::uint64_t consumed_bytes = 0;
    std::uint64_t v4l2_error_frames = 0;
    std::uint64_t timeouts = 0;
    std::uint64_t sequence_gap_events = 0;
    std::uint64_t driver_reported_drops = 0;
    std::uint64_t duplicate_sequences = 0;
    std::uint64_t backward_sequences = 0;
    std::uint64_t long_dequeue_intervals = 0;
    std::uint64_t invalid_consumer_frames = 0;

    bool have_capture_time = false;
    bool have_consume_time = false;
    bool have_previous_sequence = false;
    std::uint32_t previous_sequence = 0;
    std::chrono::steady_clock::time_point first_capture_time;
    std::chrono::steady_clock::time_point last_capture_time;
    std::chrono::steady_clock::time_point previous_capture_time;
    std::chrono::steady_clock::time_point first_consume_time;
    std::chrono::steady_clock::time_point last_consume_time;

    double max_dequeue_interval_ms = 0.0;
    double max_v4l2_buffer_hold_ms = 0.0;
    double queue_age_sum_ms = 0.0;
    double queue_age_max_ms = 0.0;
    double latency_sum_ms = 0.0;
    double latency_max_ms = 0.0;
};

}  // namespace lp2
