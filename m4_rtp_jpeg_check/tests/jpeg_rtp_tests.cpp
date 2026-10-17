#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include "lp2/jpeg_rtp_inspector.hpp"
#include "lp2/rfc2435_huffman.hpp"

namespace {

void check(bool condition, const char* name)
{
    if (!condition) {
        std::cerr << "FAIL: " << name << '\n';
        std::exit(1);
    }
}

std::vector<unsigned char> load(const char* path)
{
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    check(static_cast<bool>(file), "open reference JPEG");
    const std::streamoff length = file.tellg();
    check(length > 0, "reference length");
    std::vector<unsigned char> bytes(static_cast<std::size_t>(length));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(bytes.data()), length);
    check(static_cast<bool>(file), "read reference JPEG");
    return bytes;
}

lp2::JpegRtpReport inspect(const std::vector<unsigned char>& bytes)
{
    return lp2::inspect_jpeg_for_rtp(bytes.data(), bytes.size());
}

std::size_t marker_at(const lp2::JpegRtpReport& report, unsigned int code)
{
    for (std::size_t i = 0; i < report.markers.size(); ++i)
        if (report.markers[i].code == code) return report.markers[i].offset;
    check(false, "required marker in reference");
    return 0;
}

// Independent marker walker: expected DHT bytes come from the platform-encoded
// fixture, not the implementation's parameter header or inspector result.
void check_huffman_contract(const std::vector<unsigned char>& fixture)
{
    std::map<unsigned int, std::vector<unsigned char> > tables;
    std::size_t offset = 2;
    while (offset + 4 <= fixture.size()) {
        check(fixture[offset] == 0xff, "fixture marker alignment");
        const unsigned int marker = fixture[offset + 1];
        if (marker == 0xda) break;
        const std::size_t length = fixture[offset + 2] * 256u + fixture[offset + 3];
        check(length >= 2 && length <= fixture.size() - offset - 2,
              "fixture segment bounds");
        const std::size_t end = offset + 2 + length;
        if (marker == 0xc4) {
            std::size_t field = offset + 4;
            while (field < end) {
                check(end - field >= 17, "fixture DHT histogram bounds");
                const unsigned int selector = fixture[field++];
                std::size_t symbols = 0;
                for (std::size_t j = 0; j < 16; ++j) symbols += fixture[field + j];
                check(symbols <= end - field - 16, "fixture DHT symbol bounds");
                check(tables.count(selector) == 0, "fixture DHT unique selector");
                tables[selector] = std::vector<unsigned char>(
                    fixture.begin() + static_cast<std::ptrdiff_t>(field),
                    fixture.begin() + static_cast<std::ptrdiff_t>(field + 16 + symbols));
                field += 16 + symbols;
            }
        }
        offset = end;
    }
    check(tables.size() == 4, "four independent fixture DHT tables");
    const unsigned int order[] = {0x00, 0x10, 0x01, 0x11};
    std::vector<unsigned char> expected;
    for (unsigned int selector : order) {
        const std::vector<unsigned char>& body = tables.at(selector);
        const std::size_t count = body.size() - 16;
        const std::uint8_t kind = static_cast<std::uint8_t>(selector >> 4);
        const std::uint8_t id = static_cast<std::uint8_t>(selector & 15);
        check(lp2::rfc2435_huffman_match(kind, id, body.data(), body.data() + 16, count),
              "fixture DHT matches exact public contract");
        check(!lp2::rfc2435_huffman_match(kind, id, nullptr, body.data() + 16, count) &&
              !lp2::rfc2435_huffman_match(kind, id, body.data(), nullptr, count),
              "null inputs rejected");
        check(!lp2::rfc2435_huffman_match(kind, id, body.data(), body.data() + 16, count - 1) &&
              !lp2::rfc2435_huffman_match(kind, id, body.data(), body.data() + 16, count + 1),
              "wrong symbol lengths rejected before symbol access");
        check(!lp2::rfc2435_huffman_match(2, id, body.data(), body.data() + 16, count) &&
              !lp2::rfc2435_huffman_match(kind, 2, body.data(), body.data() + 16, count) &&
              !lp2::rfc2435_huffman_match(255, 255, body.data(), body.data() + 16, count),
              "unknown selectors rejected");
        for (std::size_t j = 0; j < body.size(); ++j) {
            std::vector<unsigned char> corrupt = body;
            corrupt[j] ^= 1;
            check(!lp2::rfc2435_huffman_match(kind, id, corrupt.data(),
                                             corrupt.data() + 16, count),
                  "every individual histogram and symbol mutation rejected");
        }
        std::vector<unsigned char> corrupt = body;
        corrupt[16] = corrupt[17];
        check(!lp2::rfc2435_huffman_match(kind, id, corrupt.data(),
                                         corrupt.data() + 16, count), "duplicate symbol rejected");
        for (std::size_t j = 0; j < 16; ++j) corrupt[j] = 255;
        check(!lp2::rfc2435_huffman_match(kind, id, corrupt.data(),
                                         corrupt.data() + 16, count), "oversized histogram rejected");
        for (std::size_t j = 0; j < 16; ++j) corrupt[j] = 0;
        corrupt[0] = static_cast<unsigned char>(count);
        check(!lp2::rfc2435_huffman_match(kind, id, corrupt.data(),
                                         corrupt.data() + 16, count), "oversubscribed tree rejected");
        const std::size_t segment = 3 + body.size();
        expected.push_back(0xff); expected.push_back(0xc4);
        expected.push_back(static_cast<unsigned char>(segment >> 8));
        expected.push_back(static_cast<unsigned char>(segment));
        expected.push_back(static_cast<unsigned char>(selector));
        expected.insert(expected.end(), body.begin(), body.end());
    }
    check(expected.size() == 432, "exact four-segment wire size");
    std::vector<unsigned char> emitted;
    lp2::append_rfc2435_huffman_markers(emitted);
    check(emitted == expected, "all DHT output bytes equal independent fixture");
    std::vector<unsigned char> prefixed(3, 0x5a), twice = prefixed;
    twice.insert(twice.end(), expected.begin(), expected.end());
    twice.insert(twice.end(), expected.begin(), expected.end());
    lp2::append_rfc2435_huffman_markers(prefixed);
    lp2::append_rfc2435_huffman_markers(prefixed);
    check(prefixed == twice, "repeated append preserves prefix and exact segment order");
}

} // namespace

int main(int argc, char** argv)
{
    check(argc == 2, "reference file argument");
    const std::vector<unsigned char> reference = load(argv[1]);
    check_huffman_contract(reference);
    const lp2::JpegRtpReport base = inspect(reference);
    check(base.structurally_parseable && base.rtp_jpeg_eligible &&
          base.rtp_type == 1 && base.width == 1280 && base.height == 720 &&
          base.quant_tables.size() == 2 && base.huffman_tables.size() == 4 &&
          base.scan_start < base.scan_end &&
          base.scan_end == reference.size() - 2,
          "reference marker-level type 1 eligibility");

    std::vector<unsigned char> changed = reference;
    changed[0] = 0;
    check(!inspect(changed).structurally_parseable, "missing SOI rejected");
    changed = reference;
    changed.pop_back();
    check(!inspect(changed).structurally_parseable, "truncated EOI rejected");
    changed = reference;
    const std::size_t dqt = marker_at(base, 0xdb);
    changed[dqt + 2] = 0xff;
    changed[dqt + 3] = 0xff;
    check(!inspect(changed).structurally_parseable,
          "out-of-bounds DQT segment rejected");
    changed = reference;
    const std::size_t sof = marker_at(base, 0xc0);
    changed[sof + 1] = 0xc2;
    check(!inspect(changed).structurally_parseable,
          "progressive SOF rejected");
    changed = reference;
    changed[sof + 11] = 0x31; // Y sampling: 3x1, not RFC type 0/1
    check(inspect(changed).structurally_parseable &&
          !inspect(changed).rtp_jpeg_eligible,
          "unsupported sampling rejected");
    changed = reference;
    const std::size_t dht = marker_at(base, 0xc4);
    changed[dht + 21] ^= 1; // first DHT symbol, lengths remain intact
    check(inspect(changed).structurally_parseable &&
          !inspect(changed).rtp_jpeg_eligible,
          "nonstandard Huffman table rejected");
    changed = reference;
    changed[base.scan_start] = 0xff;
    changed[base.scan_start + 1] = 0xc0;
    check(!inspect(changed).structurally_parseable,
          "unstuffed scan marker rejected");
    changed = reference;
    const std::size_t sos = marker_at(base, 0xda);
    const unsigned char dri[] = {0xff,0xdd,0x00,0x04,0x0f,0xa0};
    changed.insert(changed.begin() + static_cast<std::ptrdiff_t>(sos),
                   dri, dri + sizeof(dri));
    const lp2::JpegRtpReport with_dri = inspect(changed);
    check(with_dri.structurally_parseable &&
          with_dri.restart_interval == 4000 && !with_dri.rtp_jpeg_eligible,
          "DRI reported but conservatively not certified");
    std::cout << "JPEG/RTP inspection tests PASS\n";
    return 0;
}
