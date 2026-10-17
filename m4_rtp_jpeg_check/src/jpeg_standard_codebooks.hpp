// Interoperability parameters: RFC 2435 Appendix B; JPEG/T.81 Annex K.
// Each string lists hexadecimal symbols for one code length (1..16).
// This is specification data, not copied reference-program logic.
// RFC parameter material: Copyright (C) The Internet Society (1998).
// Retain LICENSES/RFC2435-notice.txt and THIRD_PARTY_NOTICES.md when distributing.
// Project-authored implementation is MIT; the RFC data are not relicensed.
#pragma once
#include <array>
namespace lp2 {
namespace jpeg_parameters {
struct LengthGroups {
    unsigned char selector;
    std::array<const char*, 16> symbols_at_length;
};
static const LengthGroups standard[] = {
    {0x00, {{
        "", "00", "0102030405", "06", "07", "08", "09", "0a",
        "0b", "", "", "", "", "", "", ""
    }}},
    {0x10, {{
        "", "0102", "03", "000411", "051221", "3141", "06135161", "072271",
        "14328191a1", "082342b1c1", "1552d1f0", "24336272", "", "", "82", "090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa"
    }}},
    {0x01, {{
        "", "000102", "03", "04", "05", "06", "07", "08",
        "09", "0a", "0b", "", "", "", "", ""
    }}},
    {0x11, {{
        "", "0001", "02", "0311", "04052131", "06124151", "076171", "13223281",
        "08144291a1b1c1", "09233352f0", "156272d1", "0a162434", "", "e1", "25f1", "1718191a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa"
    }}},
};
} // namespace jpeg_parameters
} // namespace lp2
