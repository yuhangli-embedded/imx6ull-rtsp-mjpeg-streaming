#include "lp2/frame_pool.hpp"

#include <stdexcept>

namespace lp2 {

FramePool::FramePool(
    std::size_t frame_count,
    std::size_t frame_capacity
)
{
    if (frame_count == 0 || frame_capacity == 0) {
        throw std::invalid_argument("FramePool dimensions must be non-zero");
    }

    frames_.reserve(frame_count);
    available_.reserve(frame_count);
    for (std::size_t i = 0; i < frame_count; ++i) {
        frames_.emplace_back(new Frame(frame_capacity));
        available_.push_back(frames_.back().get());
    }
}

Frame* FramePool::acquire()
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (available_.empty()) {
        return nullptr;
    }

    Frame* frame = available_.back();
    available_.pop_back();
    return frame;
}

void FramePool::release(Frame* frame)
{
    if (frame == nullptr) {
        return;
    }

    frame->size = 0;
    std::lock_guard<std::mutex> lock(mutex_);
    available_.push_back(frame);
}

std::size_t FramePool::capacity() const
{
    return frames_.size();
}

std::size_t FramePool::available() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return available_.size();
}

}  // namespace lp2
