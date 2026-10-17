#include <cstdlib>
#include <iostream>
#include <thread>

#include "lp2/bounded_frame_queue.hpp"
#include "lp2/fanout_frame_pool.hpp"

namespace {
void require(bool ok, const char* message)
{
    if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
}

int main()
{
    lp2::FanoutFramePool pool(128);
    require(pool.capacity() == 6 && pool.available() == 6, "fixed six slots");
    lp2::Frame* first = pool.acquire_capture();
    require(first && pool.available() == 5, "capture owns one slot");
    require(pool.grant(first, 2), "two downstream owners granted");
    std::thread a([&] { pool.release_ref(first); });
    std::thread b([&] { pool.release_ref(first); });
    a.join(); b.join();
    require(pool.available() == 6, "two sender releases return slot once");

    lp2::BoundedFrameQueue qa(1), qb(2);
    lp2::Frame* older = pool.acquire_capture();
    require(pool.grant(older, 2), "old frame owners granted");
    require(!qa.push_drop_oldest(older) && !qb.push_drop_oldest(older),
            "first fan-out enqueues");
    lp2::Frame* newer = pool.acquire_capture();
    require(pool.grant(newer, 2), "new frame owners granted");
    lp2::Frame* dropped = qa.push_drop_oldest(newer);
    require(dropped == older, "sender A drops oldest only");
    pool.release_ref(dropped);
    require(!qb.push_drop_oldest(newer), "sender B retains both via ownership");
    lp2::Frame* popped = nullptr;
    require(qb.pop(popped) && popped == older, "sender B still owns old frame");
    pool.release_ref(popped);
    require(qa.pop(popped) && popped == newer, "sender A owns new frame");
    pool.release_ref(popped);
    require(qb.pop(popped) && popped == newer, "sender B owns new frame");
    pool.release_ref(popped);

    lp2::Frame* slots[6] = {};
    for (unsigned int i = 0; i < 6; ++i) {
        slots[i] = pool.acquire_capture();
        require(slots[i] != nullptr, "slot acquired");
    }
    require(pool.acquire_capture() == nullptr, "pool never grows");
    for (unsigned int i = 0; i < 6; ++i) pool.release_unshared(slots[i]);
    const lp2::FanoutOwnershipStats stats = pool.stats();
    require(pool.available() == 6 &&
            stats.capture_acquires == stats.frames_returned &&
            stats.ref_acquires == stats.ref_releases &&
            stats.ownership_errors == 0,
            "fixed pool and reference accounting balanced");
    std::cout << "PASS: concurrent reference release, per-client drop-oldest, "
                 "fixed pool accounting\n";
}
