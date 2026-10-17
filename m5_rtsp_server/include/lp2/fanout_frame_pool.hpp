#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

#include "lp2/frame_pool.hpp"

namespace lp2 {

struct FanoutOwnershipStats {
    std::uint64_t capture_acquires = 0;
    std::uint64_t ref_acquires = 0;
    std::uint64_t ref_releases = 0;
    std::uint64_t frames_returned = 0;
    std::uint64_t ownership_errors = 0;
};

// Wraps M3's fixed FramePool. No per-frame control-block allocation: each of
// the six preallocated Frame slots has one fixed reference counter.
class FanoutFramePool {
public:
    explicit FanoutFramePool(std::size_t frame_capacity);
    Frame* acquire_capture();
    void release_unshared(Frame* frame);
    bool grant(Frame* frame, unsigned int downstream_owners);
    void release_ref(Frame* frame);
    std::size_t available() const { return pool_.available(); }
    std::size_t capacity() const { return pool_.capacity(); }
    FanoutOwnershipStats stats() const;
private:
    std::size_t slot_of(const Frame* frame) const;
    FramePool pool_;
    std::array<Frame*, 6> slots_;
    std::array<unsigned int, 6> refs_;
    std::array<bool, 6> in_use_;
    mutable std::mutex mutex_;
    FanoutOwnershipStats stats_;
};

} // namespace lp2
