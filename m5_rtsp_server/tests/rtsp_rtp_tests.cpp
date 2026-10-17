#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

#include "lp2/rtp_jpeg.hpp"
#include "lp2/rtp_payload_type.hpp"

namespace {
void require(bool result, const char* message)
{
    if (!result) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
}

int main(int argc, char** argv)
{
    require(argc == 2, "synthetic JPEG fixture argument");
    std::ifstream input(argv[1], std::ios::binary);
    require(input.good(), "synthetic JPEG fixture available");
    const std::vector<unsigned char> source(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    lp2::rtpjpeg::Image image;
    std::string reason;
    require(lp2::rtpjpeg::extract_type1(source.data(), source.size(), image, reason),
            reason.c_str());
    std::uint16_t sequence = 1;
    std::vector<std::vector<unsigned char> > packets;
    require(lp2::rtpjpeg::packetize(image, 1, 90000, sequence, packets, reason) &&
            !packets.empty(), "M4 default packetization");
    for (std::size_t i = 0; i < packets.size(); ++i)
        require((packets[i][1] & 0x7f) == 96, "M4 default PT96 retained");
    sequence = 1;
    require(lp2::rtpjpeg::packetize(image, 1, 90000, sequence, packets, reason) &&
            lp2::rtpjpeg::set_payload_type(packets, 26),
            "M5 static PT26 RTP header adaptation");
    for (std::size_t i = 0; i < packets.size(); ++i)
        require((packets[i][1] & 0x7f) == 26 &&
                (packets[i][1] & 0x80) == (i + 1 == packets.size() ? 0x80 : 0),
                "static PT26 and final marker");
    require(!lp2::rtpjpeg::set_payload_type(packets, 128),
            "reject PT above 7 bits");
    std::cout << "PASS: M4 PT96 unchanged; M5 PT26 and marker verified\n";
}
