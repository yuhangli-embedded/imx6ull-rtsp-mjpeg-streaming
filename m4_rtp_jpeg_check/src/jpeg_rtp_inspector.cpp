#include "lp2/jpeg_rtp_inspector.hpp"

#include <sstream>

#include "lp2/rfc2435_huffman.hpp"

namespace lp2 {
namespace {

unsigned int be16(const unsigned char* p)
{
    return (static_cast<unsigned int>(p[0]) << 8) | p[1];
}

void reason(JpegRtpReport& r, const std::string& text)
{
    r.reasons.push_back(text);
}

std::string hex_code(unsigned int code)
{
    const char digits[] = "0123456789ABCDEF";
    std::string result("FF00");
    result[2] = digits[(code >> 4) & 15];
    result[3] = digits[code & 15];
    return result;
}

bool has_quant(const JpegRtpReport& r, unsigned int id)
{
    for (std::size_t i = 0; i < r.quant_tables.size(); ++i)
        if (r.quant_tables[i].id == id) return true;
    return false;
}

bool has_standard_huffman(const JpegRtpReport& r,
                          unsigned int table_class, unsigned int id)
{
    for (std::size_t i = 0; i < r.huffman_tables.size(); ++i) {
        const HuffmanTableInfo& h = r.huffman_tables[i];
        if (h.table_class == table_class && h.id == id && h.rfc_standard)
            return true;
    }
    return false;
}

void evaluate_rtp_eligibility(JpegRtpReport& r)
{
    if (r.precision_bits != 8)
        reason(r, "SOF0 sample precision is not 8 bits");
    if (r.width == 0 || r.height == 0 || r.width > 2040 ||
        r.height > 2040 || r.width % 8 != 0 || r.height % 8 != 0)
        reason(r, "RFC 2435 width/height must be 8-pixel multiples in 1..2040");
    if (r.component_count != 3 || r.components.size() != 3) {
        reason(r, "RFC 2435 fixed types require exactly three interleaved components");
    } else {
        const JpegComponent& y = r.components[0];
        const JpegComponent& u = r.components[1];
        const JpegComponent& v = r.components[2];
        if (y.id != 1 || u.id != 2 || v.id != 3)
            reason(r, "component IDs/order must be Y=1, U=2, V=3");
        if (u.h != 1 || u.v != 1 || v.h != 1 || v.v != 1 || y.h != 2 ||
            (y.v != 1 && y.v != 2))
            reason(r, "sampling is neither RFC 2435 type 0 (4:2:2) nor type 1 (4:2:0)");
        else
            r.rtp_type = (y.v == 1 ? 0U : 1U) +
                (r.restart_interval != 0 ? 64U : 0U);
        if (y.quant != 0 || u.quant != 1 || v.quant != 1)
            reason(r, "quantization selectors must be 0 for Y and 1 for U/V");
        if (y.dc != 0 || y.ac != 0 || u.dc != 1 || u.ac != 1 ||
            v.dc != 1 || v.ac != 1)
            reason(r, "SOS Huffman selectors must be 0/0 for Y and 1/1 for U/V");
    }
    if (r.quant_tables.size() != 2 || !has_quant(r, 0) || !has_quant(r, 1))
        reason(r, "exactly DQT tables 0 and 1 are required for this fixed-type check");
    for (std::size_t i = 0; i < r.quant_tables.size(); ++i)
        if (r.quant_tables[i].precision_bits != 8)
            reason(r, "16-bit DQT is not accepted by this conservative fixed-type check");
    if (r.huffman_tables.size() != 4 ||
        !has_standard_huffman(r, 0, 0) || !has_standard_huffman(r, 1, 0) ||
        !has_standard_huffman(r, 0, 1) || !has_standard_huffman(r, 1, 1))
        reason(r, "DHT tables are missing or differ from RFC 2435 Appendix B defaults");
    if (r.restart_interval != 0 && r.components.size() == 3 &&
        r.width != 0 && r.height != 0) {
        const unsigned int hmax = r.components[0].h;
        const unsigned int vmax = r.components[0].v;
        if (hmax != 0 && vmax != 0) {
            const std::uint64_t mcus_x = (r.width + 8U * hmax - 1) /
                (8U * hmax);
            const std::uint64_t mcus_y = (r.height + 8U * vmax - 1) /
                (8U * vmax);
            const std::uint64_t expected =
                (mcus_x * mcus_y - 1) / r.restart_interval;
            if (r.restart_markers != expected)
                reason(r, "RST marker count does not match SOF dimensions and DRI interval");
        }
    }
    if (r.restart_interval != 0)
        reason(r, "DRI/RST MCU-boundary placement cannot be certified without entropy decoding");
    r.rtp_jpeg_eligible = r.reasons.empty();
}

} // namespace

const char* jpeg_marker_name(std::uint8_t code)
{
    switch (code) {
    case 0xd8: return "SOI";
    case 0xd9: return "EOI";
    case 0xc0: return "SOF0";
    case 0xda: return "SOS";
    case 0xdb: return "DQT";
    case 0xc4: return "DHT";
    case 0xdd: return "DRI";
    case 0xfe: return "COM";
    default:
        if (code >= 0xd0 && code <= 0xd7) return "RST";
        return code >= 0xe0 && code <= 0xef ? "APP" : "OTHER";
    }
}

JpegRtpReport inspect_jpeg_for_rtp(const unsigned char* data,
                                   std::size_t size)
{
    JpegRtpReport r;
    if (data == nullptr || size < 4 || data[0] != 0xff || data[1] != 0xd8) {
        reason(r, "missing SOI or file shorter than four bytes");
        return r;
    }
    r.markers.push_back(JpegMarker{0xd8, 0});
    bool have_sof = false;
    bool have_sos = false;
    bool have_dri = false;
    std::size_t p = 2;
    while (p < size) {
        if (data[p] != 0xff) {
            reason(r, "expected JPEG marker before SOS at offset " +
                      std::to_string(p));
            return r;
        }
        const std::size_t marker_offset = p;
        while (p < size && data[p] == 0xff) ++p;
        if (p == size) {
            reason(r, "truncated marker at end of file");
            return r;
        }
        const std::uint8_t code = data[p++];
        r.markers.push_back(JpegMarker{code, marker_offset});
        if (r.markers.size() > 4096) {
            reason(r, "too many JPEG markers for bounded inspection");
            return r;
        }
        if (code == 0xd9 || code == 0xd8 || code == 0x00 ||
            (code >= 0xd0 && code <= 0xd7) || code == 0x01) {
            reason(r, "unexpected standalone marker " + hex_code(code) +
                      " before SOS");
            return r;
        }
        if (p + 2 > size) {
            reason(r, "truncated segment length at offset " +
                      std::to_string(marker_offset));
            return r;
        }
        const unsigned int length = be16(data + p);
        if (length < 2 || length > size - p) {
            reason(r, "invalid segment length for " + hex_code(code) +
                      " at offset " + std::to_string(marker_offset));
            return r;
        }
        const std::size_t q = p + 2;
        const std::size_t end = p + length;
        if (code == 0xc0) {
            if (have_sof || length < 8) {
                reason(r, "duplicate or short SOF0"); return r;
            }
            have_sof = true;
            r.precision_bits = data[q];
            r.height = be16(data + q + 1);
            r.width = be16(data + q + 3);
            r.component_count = data[q + 5];
            if (r.component_count == 0 ||
                length != 8 + 3 * r.component_count) {
                reason(r, "SOF0 component count/length mismatch"); return r;
            }
            for (unsigned int i = 0; i < r.component_count; ++i) {
                const std::size_t at = q + 6 + 3 * i;
                JpegComponent c;
                c.id = data[at];
                c.h = data[at + 1] >> 4;
                c.v = data[at + 1] & 15;
                c.quant = data[at + 2];
                if (c.h == 0 || c.v == 0) {
                    reason(r, "SOF0 zero sampling factor"); return r;
                }
                for (std::size_t j = 0; j < r.components.size(); ++j)
                    if (r.components[j].id == c.id) {
                        reason(r, "duplicate SOF0 component ID"); return r;
                    }
                r.components.push_back(c);
            }
        } else if (code == 0xdb) {
            std::size_t at = q;
            while (at < end) {
                const std::uint8_t info = data[at++];
                const unsigned int precision = info >> 4;
                const unsigned int id = info & 15;
                if (precision > 1 || id > 3) {
                    reason(r, "unsupported DQT precision or table ID"); return r;
                }
                const std::size_t bytes = precision == 0 ? 64 : 128;
                if (bytes > end - at || has_quant(r, id)) {
                    reason(r, "truncated or redefined DQT table"); return r;
                }
                for (std::size_t k = 0; k < 64; ++k) {
                    const unsigned int coefficient = precision == 0
                        ? data[at + k] : be16(data + at + 2 * k);
                    if (coefficient == 0) {
                        reason(r, "zero DQT coefficient"); return r;
                    }
                }
                QuantTableInfo table(static_cast<std::uint8_t>(id),
                    static_cast<std::uint8_t>(precision == 0 ? 8 : 16));
                table.values.assign(data + at, data + at + bytes);
                r.quant_tables.push_back(table);
                at += bytes;
            }
            if (q == end) { reason(r, "empty DQT segment"); return r; }
        } else if (code == 0xc4) {
            std::size_t at = q;
            while (at < end) {
                const std::uint8_t info = data[at++];
                const unsigned int table_class = info >> 4;
                const unsigned int id = info & 15;
                if (table_class > 1 || id > 3 || end - at < 16) {
                    reason(r, "invalid DHT class, ID, or code lengths"); return r;
                }
                const unsigned char* counts = data + at;
                unsigned int symbol_count = 0;
                for (unsigned int i = 0; i < 16; ++i) symbol_count += counts[i];
                at += 16;
                if (symbol_count == 0 || symbol_count > 256 ||
                    symbol_count > end - at) {
                    reason(r, "invalid or truncated DHT symbols"); return r;
                }
                for (std::size_t j = 0; j < r.huffman_tables.size(); ++j)
                    if (r.huffman_tables[j].table_class == table_class &&
                        r.huffman_tables[j].id == id) {
                        reason(r, "redefined DHT table"); return r;
                    }
                const bool standard = rfc2435_huffman_match(
                    static_cast<std::uint8_t>(table_class),
                    static_cast<std::uint8_t>(id), counts, data + at,
                    symbol_count);
                r.huffman_tables.push_back(HuffmanTableInfo{
                    static_cast<std::uint8_t>(table_class),
                    static_cast<std::uint8_t>(id), standard});
                at += symbol_count;
            }
            if (q == end) { reason(r, "empty DHT segment"); return r; }
        } else if (code == 0xdd) {
            if (have_dri || length != 4) {
                reason(r, "duplicate or malformed DRI"); return r;
            }
            have_dri = true;
            r.restart_interval = be16(data + q);
            if (r.restart_interval == 0) {
                reason(r, "DRI restart interval is zero"); return r;
            }
        } else if (code == 0xda) {
            if (!have_sof || have_sos || length < 6) {
                reason(r, "SOS without SOF0 or malformed SOS"); return r;
            }
            have_sos = true;
            const unsigned int count = data[q];
            if (count != r.component_count || count == 0 ||
                length != 6 + 2 * count) {
                reason(r, "SOS is not a single interleaved scan"); return r;
            }
            for (unsigned int i = 0; i < count; ++i) {
                const std::size_t at = q + 1 + 2 * i;
                if (data[at] != r.components[i].id) {
                    reason(r, "SOS component order differs from SOF0"); return r;
                }
                r.components[i].dc = data[at + 1] >> 4;
                r.components[i].ac = data[at + 1] & 15;
            }
            const std::size_t at = q + 1 + 2 * count;
            if (data[at] != 0 || data[at + 1] != 63 || data[at + 2] != 0) {
                reason(r, "SOS spectral selection or approximation is not baseline");
                return r;
            }
            r.scan_start = end;
            p = end;
            break;
        } else if ((code >= 0xe0 && code <= 0xef) || code == 0xfe) {
            // APPn and COM are metadata and do not enter RTP/JPEG scan data.
        } else {
            reason(r, "unsupported JPEG marker " + hex_code(code) +
                      " before SOS");
            return r;
        }
        p = end;
    }
    if (!have_sof || !have_sos) {
        reason(r, "missing SOF0 or SOS"); return r;
    }
    unsigned int expected_rst = 0;
    while (p < size) {
        if (data[p] != 0xff) { ++p; continue; }
        const std::size_t at = p;
        while (p < size && data[p] == 0xff) ++p;
        if (p == size) { reason(r, "truncated entropy marker"); return r; }
        const std::uint8_t code = data[p++];
        if (code == 0x00 && p == at + 2) continue; // byte-stuffed FF
        if (code >= 0xd0 && code <= 0xd7) {
            if (!have_dri || code != 0xd0 + (expected_rst & 7)) {
                reason(r, "unexpected or out-of-sequence RST marker"); return r;
            }
            if (r.markers.size() >= 4096) {
                reason(r, "too many JPEG markers for bounded inspection");
                return r;
            }
            r.markers.push_back(JpegMarker{code, at});
            ++expected_rst;
            ++r.restart_markers;
            continue;
        }
        if (code == 0xd9 && p == size && p == at + 2) {
            r.scan_end = at;
            r.markers.push_back(JpegMarker{code, at});
            break;
        }
        reason(r, "unsupported marker, unstuffed FF, or trailing bytes in scan");
        return r;
    }
    if (r.scan_end == 0 || r.scan_end <= r.scan_start) {
        reason(r, "missing final EOI or empty entropy scan"); return r;
    }
    r.structurally_parseable = true;
    evaluate_rtp_eligibility(r);
    return r;
}

} // namespace lp2
