#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace lp2 { namespace rtpjpeg {

// Changes only the RTP payload-type bits, retaining the marker bit and all
// existing M4.2C JPEG fragmentation and payload bytes. PT=96 is unchanged.
inline bool set_payload_type(std::vector<std::vector<unsigned char> >& packets,
                             std::uint8_t payload_type)
{
    if (payload_type > 127) return false;
    for (std::size_t i = 0; i < packets.size(); ++i) {
        if (packets[i].size() < 12) return false;
    }
    for (std::size_t i = 0; i < packets.size(); ++i)
        packets[i][1] = static_cast<unsigned char>(
            (packets[i][1] & 0x80) | payload_type);
    return true;
}

} } // namespace lp2::rtpjpeg
