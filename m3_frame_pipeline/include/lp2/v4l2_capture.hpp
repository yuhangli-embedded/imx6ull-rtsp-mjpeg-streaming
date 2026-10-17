#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace lp2 {

struct CaptureRequest {
    std::string device = "/dev/video2";
    std::uint32_t width = 1280;
    std::uint32_t height = 720;
    std::uint32_t fps = 30;
};

struct CaptureFormat {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t pixel_format = 0;
    std::uint32_t size_image = 0;
    double configured_fps = 0.0;
    unsigned int mmap_buffers = 0;
};

struct CapturedBuffer {
    unsigned int index = 0;
    const unsigned char* data = nullptr;
    std::size_t size = 0;
    std::uint32_t sequence = 0;
    std::uint64_t capture_timestamp_us = 0;
    std::uint32_t flags = 0;
};

enum class DequeueResult {
    Frame,
    Timeout,
    Again,
    Error
};

class V4L2Capture {
public:
    V4L2Capture();
    ~V4L2Capture();

    V4L2Capture(const V4L2Capture&) = delete;
    V4L2Capture& operator=(const V4L2Capture&) = delete;

    bool open_and_configure(const CaptureRequest& request);
    bool start();
    DequeueResult dequeue(CapturedBuffer& buffer, int timeout_ms);
    bool requeue(unsigned int index);
    void stop();

    const CaptureFormat& format() const;
    const std::string& driver() const;
    const std::string& card() const;
    const std::string& error() const;

private:
    struct MappedBuffer {
        void* start = nullptr;
        std::size_t length = 0;
    };

    void cleanup();
    void set_errno_error(const char* operation);

    int fd_ = -1;
    bool streaming_ = false;
    CaptureFormat format_;
    std::vector<MappedBuffer> buffers_;
    std::string driver_;
    std::string card_;
    std::string error_;
};

}  // namespace lp2
