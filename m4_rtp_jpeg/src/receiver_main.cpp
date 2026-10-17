#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include "lp2/file_sink.hpp"
#include "lp2/frame.hpp"
#include "lp2/jpeg_validator.hpp"
#include "lp2/rtp_jpeg.hpp"

namespace {
struct Options {
    std::string listen_ip = "0.0.0.0";
    unsigned int port = 5000, duration_sec = 15, max_save_files = 10;
    std::string output_dir = "/tmp/lp2_m4_rtp_recv";
};
bool number(const char* s, unsigned int& out, bool zero)
{
    if (!s || !*s || *s == '-') return false;
    char* end = nullptr; errno = 0;
    const unsigned long n = std::strtoul(s, &end, 10);
    if (errno || *end || n > std::numeric_limits<unsigned int>::max() ||
        (!zero && n == 0)) return false;
    out = static_cast<unsigned int>(n); return true;
}
bool parse(int argc, char** argv, Options& o)
{
    for (int i = 1; i < argc; ++i) {
        const std::string key(argv[i]);
        if (key == "--help") {
            std::cout << "Usage: " << argv[0]
                << " [--listen-ip IPv4] [--port N] [--duration-sec N]"
                << " [--max-save-files N] [--output-dir PATH]\n";
            std::exit(0);
        }
        if (++i >= argc) return false;
        if (key == "--listen-ip") o.listen_ip = argv[i];
        else if (key == "--output-dir") o.output_dir = argv[i];
        else if (key == "--port") {
            if (!number(argv[i], o.port, false) || o.port > 65535) return false;
        } else if (key == "--duration-sec") {
            if (!number(argv[i], o.duration_sec, false)) return false;
        } else if (key == "--max-save-files") {
            if (!number(argv[i], o.max_save_files, true)) return false;
        } else return false;
    }
    return !o.output_dir.empty();
}
std::uint64_t now_ms()
{
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
}

int main(int argc, char** argv)
{
    Options o;
    if (!parse(argc, argv, o)) {
        std::cerr << "Invalid arguments; use --help\n"; return 2;
    }
    struct sockaddr_in bind_to {};
    bind_to.sin_family = AF_INET;
    bind_to.sin_port = htons(static_cast<std::uint16_t>(o.port));
    if (inet_pton(AF_INET, o.listen_ip.c_str(), &bind_to.sin_addr) != 1) {
        std::cerr << "--listen-ip must be numeric IPv4\n"; return 2;
    }
    lp2::FileSink sink(o.output_dir, o.max_save_files);
    if (!sink.initialize()) { std::cerr << sink.error() << '\n'; return 1; }
    const int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) { std::cerr << std::strerror(errno) << '\n'; return 1; }
    const int requested = 4 * 1024 * 1024;
    if (setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &requested, sizeof(requested)) < 0 ||
        bind(fd, reinterpret_cast<struct sockaddr*>(&bind_to), sizeof(bind_to)) < 0 ||
        fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK) < 0) {
        std::cerr << "RTP receiver socket setup: " << std::strerror(errno) << '\n';
        close(fd); return 1;
    }
    int actual = 0; socklen_t actual_len = sizeof(actual);
    getsockopt(fd, SOL_SOCKET, SO_RCVBUF, &actual, &actual_len);
    std::cout << "RTP listen: " << o.listen_ip << ':' << o.port
              << " SO_RCVBUF actual: " << actual << " bytes\n";
    lp2::rtpjpeg::Reassembler receiver;
    const std::chrono::steady_clock::time_point deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(o.duration_sec);
    bool io_error = false;
    while (std::chrono::steady_clock::now() < deadline) {
        receiver.expire(now_ms());
        struct pollfd waitfd {}; waitfd.fd = fd; waitfd.events = POLLIN;
        const int ready = poll(&waitfd, 1, 20);
        if (ready < 0) {
            if (errno == EINTR) continue;
            io_error = true; break;
        }
        if (ready > 0 && (waitfd.revents & (POLLERR | POLLNVAL))) {
            io_error = true; break;
        }
        if (ready == 0 || !(waitfd.revents & POLLIN)) continue;
        for (;;) {
            if (std::chrono::steady_clock::now() >= deadline) break;
            unsigned char packet[2048];
            const ssize_t n = recvfrom(fd, packet, sizeof(packet), 0, nullptr, nullptr);
            if (n < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) break;
                if (errno == EINTR) continue;
                io_error = true; break;
            }
            std::vector<unsigned char> jpeg;
            if (!receiver.accept(packet, static_cast<std::size_t>(n),
                                 now_ms(), jpeg)) continue;
            lp2::Frame frame(0);
            frame.storage.swap(jpeg);
            frame.size = frame.storage.size();
            // The reassembler already checks a complete JPEG; FileSink checks
            // strict SOI/EOI again before writing.
            sink.consume(frame);
        }
        if (io_error) break;
    }
    receiver.expire(now_ms() + 500);
    close(fd);
    const lp2::rtpjpeg::ReceiverStats& s = receiver.stats();
    std::cout << "RTP packets received: " << s.received_packets
              << "\nInvalid packets: " << s.invalid_packets
              << "\nDuplicate fragments: " << s.duplicate_fragments
              << "\nIncomplete frame timeouts: " << s.incomplete_timeouts
              << "\nReassembly capacity drops: " << s.capacity_drops
              << "\nReassembled frames: " << s.completed_frames
              << "\nJPEG validation failures: " << s.jpeg_validation_failures
              << "\nSaved files: " << sink.saved_files()
              << "\nFile write failures: " << sink.write_failures() << '\n';
    if (io_error) std::cerr << "RTP receiver socket I/O error\n";
    return io_error || sink.write_failures() ? 1 : 0;
}
