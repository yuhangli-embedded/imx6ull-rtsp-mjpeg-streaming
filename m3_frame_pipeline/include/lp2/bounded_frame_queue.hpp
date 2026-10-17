#pragma once

#include <condition_variable>
#include <cstddef>
#include <mutex>
#include <vector>

#include "lp2/frame.hpp"

namespace lp2 {

class BoundedFrameQueue {
public:
    explicit BoundedFrameQueue(std::size_t capacity);

    BoundedFrameQueue(const BoundedFrameQueue&) = delete;
    BoundedFrameQueue& operator=(const BoundedFrameQueue&) = delete;

    Frame* push_drop_oldest(Frame* frame);
    bool pop(Frame*& frame);
    Frame* drop_oldest();
    void close();

    std::size_t current_depth() const;
    std::size_t max_depth() const;
    std::size_t capacity() const;

private:
    mutable std::mutex mutex_;
    std::condition_variable not_empty_;
    std::vector<Frame*> slots_;
    std::size_t head_ = 0;
    std::size_t size_ = 0;
    std::size_t max_depth_ = 0;
    bool closed_ = false;
};

}  // namespace lp2
