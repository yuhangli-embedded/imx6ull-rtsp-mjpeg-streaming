#include <chrono>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <thread>

#include "lp2/fanout_frame_pool.hpp"
#include "lp2/rtsp_client_session.hpp"

// No socket is opened by this test double. The real sender thread, fixed
// FramePool, bounded queues, and reference-release paths are under test.
namespace lp2 {
RtpSink::RtpSink(const std::string&, std::uint16_t, unsigned int, unsigned int,
                 std::uint8_t, std::uint16_t) {}
RtpSink::~RtpSink() {}
bool RtpSink::consume(const Frame& frame) { return consume_prevalidated(frame); }
bool RtpSink::consume_prevalidated(const Frame& frame)
{
    ++submitted_frames_;
    ++datagrams_;
    bytes_ += frame.size;
    return true;
}
}

namespace {
void require(bool condition, const char* message)
{
    if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}

void send_frame(lp2::FanoutFramePool& pool,
                lp2::RtspClientSession& a,
                lp2::RtspClientSession* b)
{
    lp2::Frame* frame = pool.acquire_capture();
    require(frame != nullptr, "fixed pool has a free Frame");
    frame->size = 4;
    require(pool.grant(frame, b ? 2 : 1), "downstream references granted");
    lp2::Frame* dropped = nullptr;
    require(a.offer(frame, dropped), "A accepts Frame");
    if (dropped) pool.release_ref(dropped);
    if (b) {
        dropped = nullptr;
        require(b->offer(frame, dropped), "B accepts Frame");
        if (dropped) pool.release_ref(dropped);
    }
}

void run(unsigned int b_delay_ms, bool expect_b_drop)
{
    lp2::FanoutFramePool pool(128);
    std::shared_ptr<lp2::RtpSink> sink_a(new lp2::RtpSink("", 0, 0, 0));
    std::shared_ptr<lp2::RtpSink> sink_b(new lp2::RtpSink("", 0, 0, 0));
    lp2::RtspClientSession a(1, "A", -1, "", 0, 0, -1, sink_a, pool, 0);
    lp2::RtspClientSession b(2, "B", -1, "", 0, 0, -1, sink_b, pool,
                             b_delay_ms);
    require(a.start_sender() && b.start_sender(), "sender threads started");
    a.set_playing(true);
    b.set_playing(true);
    for (unsigned int i = 0; i < 12; ++i) {
        send_frame(pool, a, &b);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(120));
    const lp2::RtspClientStats b_stats = b.stop_and_join();
    require(b_stats.artificial_send_delay_ms == b_delay_ms,
            "B delay recorded independently");
    require((b_stats.sender_queue_dropped > 0) == expect_b_drop,
            "B bounded queue has expected backpressure");
    if (expect_b_drop)
        require(b_stats.max_sender_queue_depth == 2,
                "slow B queue reaches its fixed capacity");
    require(b_stats.rtp_frames_submitted > 0,
            "B continues submitting some Frames");
    require(b_stats.current_sender_queue_depth == 0,
            "B sender queue drained on stop");
    for (unsigned int i = 0; i < 5; ++i) {
        send_frame(pool, a, nullptr);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    const lp2::RtspClientStats a_stats = a.stop_and_join();
    require(a_stats.sender_queue_dropped == 0,
            "A sender queue unaffected by B delay and disconnect");
    require(a_stats.rtp_frames_submitted == 17,
            "A keeps sending after B disconnects");
    require(a_stats.current_sender_queue_depth == 0,
            "A sender queue drained on stop");
    const lp2::FanoutOwnershipStats ownership = pool.stats();
    require(pool.available() == 6 &&
            ownership.capture_acquires == ownership.frames_returned &&
            ownership.ref_acquires == ownership.ref_releases &&
            ownership.ownership_errors == 0,
            "all shared Frame references returned exactly once");
}
}

int main()
{
    run(0, false);
    run(80, true);
    std::cout << "PASS: zero-delay regression, slow-client drop-oldest, "
                 "fast-client isolation and reference accounting\n";
}
