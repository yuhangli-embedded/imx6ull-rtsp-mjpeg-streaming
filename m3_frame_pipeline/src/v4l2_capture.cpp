#include "lp2/v4l2_capture.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sstream>

#include <linux/videodev2.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

namespace lp2 {
namespace {

int xioctl(int fd, unsigned long request, void* argument)
{
    int result;
    do {
        result = ioctl(fd, request, argument);
    } while (result == -1 && errno == EINTR);
    return result;
}

}  // namespace

V4L2Capture::V4L2Capture() = default;

V4L2Capture::~V4L2Capture()
{
    cleanup();
}

bool V4L2Capture::open_and_configure(const CaptureRequest& request)
{
    cleanup();
    error_.clear();

    fd_ = open(request.device.c_str(), O_RDWR | O_NONBLOCK);
    if (fd_ < 0) {
        set_errno_error("open");
        return false;
    }

    v4l2_capability capability {};
    if (xioctl(fd_, VIDIOC_QUERYCAP, &capability) < 0) {
        set_errno_error("VIDIOC_QUERYCAP");
        cleanup();
        return false;
    }

    driver_ = reinterpret_cast<const char*>(capability.driver);
    card_ = reinterpret_cast<const char*>(capability.card);
    std::uint32_t capabilities = capability.capabilities;
    if (capabilities & V4L2_CAP_DEVICE_CAPS) {
        capabilities = capability.device_caps;
    }
    if (!(capabilities & V4L2_CAP_VIDEO_CAPTURE) ||
        !(capabilities & V4L2_CAP_STREAMING)) {
        error_ = "Device lacks V4L2 capture or streaming capability";
        cleanup();
        return false;
    }

    v4l2_format format {};
    format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    format.fmt.pix.width = request.width;
    format.fmt.pix.height = request.height;
    format.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
    format.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(fd_, VIDIOC_S_FMT, &format) < 0) {
        set_errno_error("VIDIOC_S_FMT");
        cleanup();
        return false;
    }

    format_.width = format.fmt.pix.width;
    format_.height = format.fmt.pix.height;
    format_.pixel_format = format.fmt.pix.pixelformat;
    format_.size_image = format.fmt.pix.sizeimage;

    if (format_.width != request.width ||
        format_.height != request.height ||
        format_.pixel_format != V4L2_PIX_FMT_MJPEG ||
        format_.size_image == 0) {
        error_ = "Camera did not accept the requested MJPEG format";
        cleanup();
        return false;
    }

    v4l2_streamparm parameters {};
    parameters.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    parameters.parm.capture.timeperframe.numerator = 1;
    parameters.parm.capture.timeperframe.denominator = request.fps;
    const bool set_parameters =
        xioctl(fd_, VIDIOC_S_PARM, &parameters) == 0;

    v4l2_streamparm actual_parameters {};
    actual_parameters.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd_, VIDIOC_G_PARM, &actual_parameters) == 0) {
        parameters = actual_parameters;
    } else if (!set_parameters) {
        set_errno_error("VIDIOC_S_PARM/VIDIOC_G_PARM");
        cleanup();
        return false;
    }

    const std::uint32_t numerator =
        parameters.parm.capture.timeperframe.numerator;
    const std::uint32_t denominator =
        parameters.parm.capture.timeperframe.denominator;
    if (numerator != 0) {
        format_.configured_fps =
            static_cast<double>(denominator) / numerator;
    }

    v4l2_requestbuffers request_buffers {};
    request_buffers.count = 4;
    request_buffers.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    request_buffers.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd_, VIDIOC_REQBUFS, &request_buffers) < 0) {
        set_errno_error("VIDIOC_REQBUFS");
        cleanup();
        return false;
    }
    if (request_buffers.count < 2) {
        error_ = "Driver returned fewer than two mmap buffers";
        cleanup();
        return false;
    }

    buffers_.resize(request_buffers.count);
    format_.mmap_buffers = request_buffers.count;
    for (unsigned int i = 0; i < request_buffers.count; ++i) {
        v4l2_buffer buffer {};
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.index = i;
        if (xioctl(fd_, VIDIOC_QUERYBUF, &buffer) < 0) {
            set_errno_error("VIDIOC_QUERYBUF");
            cleanup();
            return false;
        }

        void* address = mmap(
            nullptr,
            buffer.length,
            PROT_READ | PROT_WRITE,
            MAP_SHARED,
            fd_,
            buffer.m.offset
        );
        if (address == MAP_FAILED) {
            set_errno_error("mmap");
            cleanup();
            return false;
        }
        buffers_[i].start = address;
        buffers_[i].length = buffer.length;
    }

    return true;
}

bool V4L2Capture::start()
{
    if (fd_ < 0 || streaming_) {
        error_ = "Capture device is not ready to start";
        return false;
    }

    for (unsigned int i = 0; i < buffers_.size(); ++i) {
        v4l2_buffer buffer {};
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.index = i;
        if (xioctl(fd_, VIDIOC_QBUF, &buffer) < 0) {
            set_errno_error("VIDIOC_QBUF");
            return false;
        }
    }

    v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd_, VIDIOC_STREAMON, &type) < 0) {
        set_errno_error("VIDIOC_STREAMON");
        return false;
    }
    streaming_ = true;
    return true;
}

DequeueResult V4L2Capture::dequeue(
    CapturedBuffer& captured,
    int timeout_ms
)
{
    pollfd descriptor {};
    descriptor.fd = fd_;
    descriptor.events = POLLIN;
    const int poll_result = poll(&descriptor, 1, timeout_ms);
    if (poll_result < 0) {
        if (errno == EINTR) {
            return DequeueResult::Again;
        }
        set_errno_error("poll");
        return DequeueResult::Error;
    }
    if (poll_result == 0) {
        return DequeueResult::Timeout;
    }
    if (descriptor.revents & (POLLNVAL | POLLHUP)) {
        error_ = "poll reported a disconnected or invalid device";
        return DequeueResult::Error;
    }

    v4l2_buffer buffer {};
    buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buffer.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd_, VIDIOC_DQBUF, &buffer) < 0) {
        if (errno == EAGAIN) {
            return DequeueResult::Again;
        }
        set_errno_error("VIDIOC_DQBUF");
        return DequeueResult::Error;
    }
    if (buffer.index >= buffers_.size() ||
        buffer.bytesused > buffers_[buffer.index].length) {
        error_ = "Driver returned an invalid mmap buffer";
        return DequeueResult::Error;
    }

    captured.index = buffer.index;
    captured.data = static_cast<const unsigned char*>(
        buffers_[buffer.index].start
    );
    captured.size = buffer.bytesused;
    captured.sequence = buffer.sequence;
    captured.capture_timestamp_us =
        static_cast<std::uint64_t>(buffer.timestamp.tv_sec) * 1000000ULL +
        static_cast<std::uint64_t>(buffer.timestamp.tv_usec);
    captured.flags = buffer.flags;
    return DequeueResult::Frame;
}

bool V4L2Capture::requeue(unsigned int index)
{
    if (index >= buffers_.size()) {
        error_ = "Attempted to requeue an invalid mmap buffer";
        return false;
    }

    v4l2_buffer buffer {};
    buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buffer.memory = V4L2_MEMORY_MMAP;
    buffer.index = index;
    if (xioctl(fd_, VIDIOC_QBUF, &buffer) < 0) {
        set_errno_error("VIDIOC_QBUF");
        return false;
    }
    return true;
}

void V4L2Capture::stop()
{
    if (!streaming_) {
        return;
    }

    v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd_, VIDIOC_STREAMOFF, &type) < 0) {
        set_errno_error("VIDIOC_STREAMOFF");
    }
    streaming_ = false;
}

const CaptureFormat& V4L2Capture::format() const
{
    return format_;
}

const std::string& V4L2Capture::driver() const
{
    return driver_;
}

const std::string& V4L2Capture::card() const
{
    return card_;
}

const std::string& V4L2Capture::error() const
{
    return error_;
}

void V4L2Capture::cleanup()
{
    stop();
    for (std::size_t i = 0; i < buffers_.size(); ++i) {
        if (buffers_[i].start != nullptr &&
            buffers_[i].start != MAP_FAILED) {
            munmap(buffers_[i].start, buffers_[i].length);
        }
    }
    buffers_.clear();
    if (fd_ >= 0) {
        close(fd_);
        fd_ = -1;
    }
}

void V4L2Capture::set_errno_error(const char* operation)
{
    std::ostringstream stream;
    stream << operation << " failed: " << std::strerror(errno);
    error_ = stream.str();
}

}  // namespace lp2
