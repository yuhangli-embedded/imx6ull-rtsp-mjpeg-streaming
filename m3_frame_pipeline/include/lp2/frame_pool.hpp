#pragma once

#include <cstddef>
#include <memory>
#include <mutex>
#include <vector>

#include "lp2/frame.hpp"

namespace lp2 {

class FramePool {
public:
    FramePool(std::size_t frame_count, std::size_t frame_capacity);

    FramePool(const FramePool&) = delete;
    FramePool& operator=(const FramePool&) = delete;

    Frame* acquire();
    void release(Frame* frame);

    std::size_t capacity() const;
    std::size_t available() const;

private:
    mutable std::mutex mutex_;
    std::vector<std::unique_ptr<Frame> > frames_;
    std::vector<Frame*> available_;
};

}  // namespace lp2
