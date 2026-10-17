#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace lp2 {

// Exact fixed Huffman tables for RFC 2435 types 0/1/64/65 (Appendix B).
// counts addresses 16 bytes; symbols addresses symbol_count bytes.
// Unsupported selectors, null pointers and non-exact tables return false.
bool rfc2435_huffman_match(std::uint8_t table_class, std::uint8_t id,
                           const unsigned char* counts,
                           const unsigned char* symbols,
                           std::size_t symbol_count);

// Append four canonical RFC 2435 Appendix B DHT JPEG marker segments.
void append_rfc2435_huffman_markers(std::vector<unsigned char>& jpeg);

} // namespace lp2
