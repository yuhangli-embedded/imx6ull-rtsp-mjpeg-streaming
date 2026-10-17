#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace lp2 {

struct JpegMarker {
    JpegMarker(std::uint8_t marker_code, std::size_t marker_offset)
        : code(marker_code), offset(marker_offset) {}
    std::uint8_t code = 0;
    std::size_t offset = 0;
};

struct JpegComponent {
    std::uint8_t id = 0;
    std::uint8_t h = 0;
    std::uint8_t v = 0;
    std::uint8_t quant = 0;
    std::uint8_t dc = 0;
    std::uint8_t ac = 0;
};

struct QuantTableInfo {
    QuantTableInfo(std::uint8_t table_id, std::uint8_t bits)
        : id(table_id), precision_bits(bits) {}
    std::uint8_t id = 0;
    std::uint8_t precision_bits = 0;
    // Raw JPEG DQT order (zig-zag); populated only for a parsed table.
    std::vector<unsigned char> values;
};

struct HuffmanTableInfo {
    HuffmanTableInfo(std::uint8_t klass, std::uint8_t table_id, bool standard)
        : table_class(klass), id(table_id), rfc_standard(standard) {}
    std::uint8_t table_class = 0; // 0=DC, 1=AC
    std::uint8_t id = 0;
    bool rfc_standard = false;
};

struct JpegRtpReport {
    bool structurally_parseable = false;
    bool rtp_jpeg_eligible = false;
    unsigned int rtp_type = 0;
    unsigned int precision_bits = 0;
    unsigned int width = 0;
    unsigned int height = 0;
    unsigned int component_count = 0;
    unsigned int restart_interval = 0;
    unsigned int restart_markers = 0;
    std::size_t scan_start = 0;
    std::size_t scan_end = 0; // exclusive; EOI begins here
    std::vector<JpegMarker> markers;
    std::vector<JpegComponent> components;
    std::vector<QuantTableInfo> quant_tables;
    std::vector<HuffmanTableInfo> huffman_tables;
    std::vector<std::string> reasons;
};

JpegRtpReport inspect_jpeg_for_rtp(const unsigned char* data,
                                   std::size_t size);
const char* jpeg_marker_name(std::uint8_t code);

} // namespace lp2
