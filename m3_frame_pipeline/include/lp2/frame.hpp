#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace lp2 {

struct Frame {
    explicit Frame(std::size_t capacity)
        : storage(capacity)
    {
    }

    std::uint32_t sequence = 0;
    std::uint64_t capture_timestamp_us = 0;
    std::size_t size = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t pixel_format = 0;
    std::chrono::steady_clock::time_point application_capture_time;
    std::vector<unsigned char> storage;
};

}  // namespace lp2
