#include "lp2/bounded_frame_queue.hpp"

#include <stdexcept>

namespace lp2 {

BoundedFrameQueue::BoundedFrameQueue(std::size_t capacity)
    : slots_(capacity, nullptr)
{
    if (capacity == 0) {
        throw std::invalid_argument("Queue capacity must be non-zero");
    }
}

Frame* BoundedFrameQueue::push_drop_oldest(Frame* frame)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (closed_) {
        return frame;
    }

    Frame* dropped = nullptr;
    if (size_ == slots_.size()) {
        dropped = slots_[head_];
        slots_[head_] = frame;
        head_ = (head_ + 1) % slots_.size();
    } else {
        const std::size_t tail = (head_ + size_) % slots_.size();
        slots_[tail] = frame;
        ++size_;
        if (size_ > max_depth_) {
            max_depth_ = size_;
        }
    }

    not_empty_.notify_one();
    return dropped;
}

bool BoundedFrameQueue::pop(Frame*& frame)
{
    std::unique_lock<std::mutex> lock(mutex_);
    not_empty_.wait(lock, [this] { return closed_ || size_ != 0; });
    if (size_ == 0) {
        frame = nullptr;
        return false;
    }

    frame = slots_[head_];
    slots_[head_] = nullptr;
    head_ = (head_ + 1) % slots_.size();
    --size_;
    return true;
}

Frame* BoundedFrameQueue::drop_oldest()
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (size_ == 0) {
        return nullptr;
    }

    Frame* frame = slots_[head_];
    slots_[head_] = nullptr;
    head_ = (head_ + 1) % slots_.size();
    --size_;
    return frame;
}

void BoundedFrameQueue::close()
{
    std::lock_guard<std::mutex> lock(mutex_);
    closed_ = true;
    not_empty_.notify_all();
}

std::size_t BoundedFrameQueue::current_depth() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return size_;
}

std::size_t BoundedFrameQueue::max_depth() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return max_depth_;
}

std::size_t BoundedFrameQueue::capacity() const
{
    return slots_.size();
}

}  // namespace lp2
