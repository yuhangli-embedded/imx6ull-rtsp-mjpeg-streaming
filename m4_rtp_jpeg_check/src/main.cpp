#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

#include "lp2/jpeg_rtp_inspector.hpp"

namespace {

const std::size_t kMaxInputBytes = 16 * 1024 * 1024;

bool load_read_only(const std::string& path,
                    std::vector<unsigned char>& bytes,
                    std::string& error)
{
    std::ifstream input(path.c_str(), std::ios::binary | std::ios::ate);
    if (!input) { error = "cannot open file"; return false; }
    const std::streamoff length = input.tellg();
    if (length < 0 || static_cast<std::uint64_t>(length) > kMaxInputBytes) {
        error = "file length invalid or above 16 MiB inspection limit";
        return false;
    }
    bytes.resize(static_cast<std::size_t>(length));
    input.seekg(0, std::ios::beg);
    if (!bytes.empty()) {
        input.read(reinterpret_cast<char*>(bytes.data()),
                   static_cast<std::streamsize>(bytes.size()));
        if (!input) { error = "short read or I/O failure"; return false; }
    }
    return true;
}

void print_report(const std::string& path, std::size_t size,
                  const lp2::JpegRtpReport& r)
{
    std::cout << "FILE: " << path << "\nbytes: " << size << "\nmarkers:";
    for (std::size_t i = 0; i < r.markers.size(); ++i) {
        const lp2::JpegMarker& m = r.markers[i];
        std::cout << ' ' << lp2::jpeg_marker_name(m.code) << "@" << m.offset;
    }
    std::cout << "\nSOF0: " << r.width << 'x' << r.height
              << ", precision=" << r.precision_bits
              << ", components=" << r.component_count << '\n';
    for (std::size_t i = 0; i < r.components.size(); ++i) {
        const lp2::JpegComponent& c = r.components[i];
        std::cout << "  component " << static_cast<unsigned int>(c.id)
                  << ": H=" << static_cast<unsigned int>(c.h)
                  << " V=" << static_cast<unsigned int>(c.v)
                  << " DQT=" << static_cast<unsigned int>(c.quant)
                  << " DC=" << static_cast<unsigned int>(c.dc)
                  << " AC=" << static_cast<unsigned int>(c.ac) << '\n';
    }
    std::cout << "DQT tables: " << r.quant_tables.size() << '\n';
    for (std::size_t i = 0; i < r.quant_tables.size(); ++i) {
        const lp2::QuantTableInfo& q = r.quant_tables[i];
        std::cout << "  id=" << static_cast<unsigned int>(q.id)
                  << " precision=" << static_cast<unsigned int>(q.precision_bits)
                  << " bits\n";
    }
    std::cout << "DHT tables: " << r.huffman_tables.size() << '\n';
    for (std::size_t i = 0; i < r.huffman_tables.size(); ++i) {
        const lp2::HuffmanTableInfo& h = r.huffman_tables[i];
        std::cout << "  " << (h.table_class == 0 ? "DC" : "AC")
                  << " id=" << static_cast<unsigned int>(h.id)
                  << " RFC2435-default=" << (h.rfc_standard ? "yes" : "no")
                  << '\n';
    }
    std::cout << "DRI interval: " << r.restart_interval
              << "; RST markers: " << r.restart_markers << '\n'
              << "SOS scan bytes: [" << r.scan_start << ", " << r.scan_end
              << ") length=" << (r.scan_end >= r.scan_start
                                    ? r.scan_end - r.scan_start : 0)
              << "\nEOI: " << (r.scan_end != 0 ? "present" : "not confirmed")
              << "\nRFC2435 fixed-type marker eligibility: "
              << (r.rtp_jpeg_eligible ? "YES" : "NO") << '\n';
    if (r.rtp_jpeg_eligible)
        std::cout << "candidate RTP/JPEG type: " << r.rtp_type
                  << " (Q would require explicit table handling)\n";
    for (std::size_t i = 0; i < r.reasons.size(); ++i)
        std::cout << "reason: " << r.reasons[i] << '\n';
    std::cout << "Note: marker-level check only; entropy is not decoded. "
              << "No RTP packets are generated.\n\n";
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 2 || (argc == 2 && std::string(argv[1]) == "--help")) {
        std::cout << "Usage: " << argv[0] << " FILE.jpg [FILE2.jpg ...]\n";
        return argc < 2 ? 2 : 0;
    }
    bool all_eligible = true;
    for (int i = 1; i < argc; ++i) {
        const std::string path(argv[i]);
        std::vector<unsigned char> bytes;
        std::string error;
        if (!load_read_only(path, bytes, error)) {
            std::cout << "FILE: " << path << "\n"
                      << "RFC2435 fixed-type marker eligibility: NO\n"
                      << "reason: " << error << "\n\n";
            all_eligible = false;
            continue;
        }
        const lp2::JpegRtpReport report = lp2::inspect_jpeg_for_rtp(
            bytes.data(), bytes.size());
        print_report(path, bytes.size(), report);
        if (!report.rtp_jpeg_eligible) all_eligible = false;
    }
    return all_eligible ? 0 : 1;
}
