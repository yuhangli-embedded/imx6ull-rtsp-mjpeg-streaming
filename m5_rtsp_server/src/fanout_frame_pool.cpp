#include "lp2/fanout_frame_pool.hpp"

#include <stdexcept>

namespace lp2 {

FanoutFramePool::FanoutFramePool(std::size_t frame_capacity)
    : pool_(6, frame_capacity), slots_(), refs_(), in_use_()
{
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        slots_[i] = pool_.acquire();
        if (!slots_[i]) throw std::runtime_error("FramePool initialization failed");
    }
    for (std::size_t i = 0; i < slots_.size(); ++i) pool_.release(slots_[i]);
}

std::size_t FanoutFramePool::slot_of(const Frame* frame) const
{
    for (std::size_t i = 0; i < slots_.size(); ++i)
        if (slots_[i] == frame) return i;
    return slots_.size();
}

Frame* FanoutFramePool::acquire_capture()
{
    Frame* frame = pool_.acquire();
    if (!frame) return nullptr;
    std::lock_guard<std::mutex> lock(mutex_);
    const std::size_t slot = slot_of(frame);
    if (slot == slots_.size() || in_use_[slot] || refs_[slot] != 0) {
        ++stats_.ownership_errors;
        pool_.release(frame);
        return nullptr;
    }
    in_use_[slot] = true;
    ++stats_.capture_acquires;
    return frame;
}

void FanoutFramePool::release_unshared(Frame* frame)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const std::size_t slot = slot_of(frame);
    if (slot == slots_.size() || !in_use_[slot] || refs_[slot] != 0) {
        ++stats_.ownership_errors;
        return;
    }
    in_use_[slot] = false;
    pool_.release(frame);
    ++stats_.frames_returned;
}

bool FanoutFramePool::grant(Frame* frame, unsigned int downstream_owners)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const std::size_t slot = slot_of(frame);
    if (slot == slots_.size() || !in_use_[slot] || refs_[slot] != 0 ||
        downstream_owners == 0 || downstream_owners > 2) {
        ++stats_.ownership_errors;
        return false;
    }
    refs_[slot] = downstream_owners;
    stats_.ref_acquires += downstream_owners;
    return true;
}

void FanoutFramePool::release_ref(Frame* frame)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const std::size_t slot = slot_of(frame);
    if (slot == slots_.size() || !in_use_[slot] || refs_[slot] == 0) {
        ++stats_.ownership_errors;
        return;
    }
    --refs_[slot];
    ++stats_.ref_releases;
    if (refs_[slot] == 0) {
        in_use_[slot] = false;
        pool_.release(frame);
        ++stats_.frames_returned;
    }
}

FanoutOwnershipStats FanoutFramePool::stats() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return stats_;
}

} // namespace lp2
