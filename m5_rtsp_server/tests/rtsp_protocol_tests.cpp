#include <cstdlib>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include "lp2/rtsp_protocol.hpp"

namespace {
void require(bool ok, const char* why)
{
    if (!ok) { std::cerr << "FAIL: " << why << '\n'; std::exit(1); }
}
}

int main()
{
    using namespace lp2::rtsp;
    Request req; std::size_t used = 0; std::string error;
    const std::string setup =
        "SETUP rtsp://192.168.50.2:8554/live/track1 RTSP/1.0\r\n"
        "CSeq: 3\r\n"
        "Transport: RTP/AVP/UDP;unicast;client_port=5000-5001;mode=\"PLAY\"\r\n"
        "\r\n";
    require(parse_request(setup.substr(0, 17), req, used, error) ==
            ParseResult::NeedMore, "partial TCP request");
    require(parse_request(setup + setup, req, used, error) ==
            ParseResult::Complete && used == setup.size() &&
            req.path == "/live/track1" && req.cseq == "3",
            "pipelined SETUP parse");
    std::uint16_t rtp = 0, rtcp = 0;
    require(parse_client_ports(header(req, "transport"), rtp, rtcp) &&
            rtp == 5000 && rtcp == 5001, "ffplay UDP transport");
    require(parse_client_ports("RTP/AVP/TCP;unicast;interleaved=0-1,"
            "RTP/AVP;unicast;client_port=6000-6001", rtp, rtcp) &&
            rtp == 6000, "transport alternative selection");
    require(!parse_client_ports("RTP/AVP/TCP;unicast;interleaved=0-1", rtp, rtcp),
            "reject TCP interleaved");
    require(!parse_client_ports("RTP/AVP;multicast;client_port=5000-5001", rtp, rtcp),
            "reject multicast");
    require(!parse_client_ports("RTP/AVP;unicast;client_port=5001-5002", rtp, rtcp),
            "reject odd RTP port");
    require(!parse_client_ports("RTP/AVP;unicast;client_port=5000-5002", rtp, rtcp),
            "reject nonadjacent RTCP port");
    require(!parse_client_ports("RTP/AVP;unicast;destination=1.2.3.4;"
            "client_port=5000-5001", rtp, rtcp), "reject third-party destination");
    require(session_token("abc123;timeout=120") == "abc123", "session token");
    const std::string describe =
        "DESCRIBE rtsp://192.168.50.2:8554/live RTSP/1.0\r\nCSeq: 2\r\n\r\n";
    require(parse_request(describe, req, used, error) == ParseResult::Complete &&
            req.path == "/live", "DESCRIBE URI");
    const std::string body = sdp("192.168.50.2");
    require(body.find("m=video 0 RTP/AVP 26\r\n") != std::string::npos &&
            body.find("a=control:track1\r\n") != std::string::npos &&
            body.find("c=IN IP4 192.168.50.2\r\n") != std::string::npos,
            "SDP PT26 and track");
    std::vector<std::pair<std::string, std::string> > headers;
    headers.push_back(std::make_pair("Content-Type", "application/sdp"));
    const std::string reply = response(200, "OK", req.cseq, headers, body);
    require(reply.find("RTSP/1.0 200 OK\r\nCSeq: 2\r\n") == 0 &&
            reply.find("Content-Type: application/sdp\r\n") != std::string::npos &&
            reply.find("Content-Length: " + std::to_string(body.size()) +
                       "\r\n\r\n" + body) != std::string::npos,
            "exact CRLF response and SDP byte length");
    require(parse_request("PLAY /live RTSP/1.0\r\n\r\n", req, used, error) ==
            ParseResult::Invalid, "missing CSeq");
    require(parse_request("PLAY /live RTSP/1.0\r\nCSeq: 4\r\nCSeq: 5\r\n\r\n",
            req, used, error) == ParseResult::Invalid, "duplicate header");
    require(parse_request("PLAY /live RTSP/1.0\r\nCSeq: 4\r\n"
            "Content-Length: 99999\r\n\r\n", req, used, error) ==
            ParseResult::Invalid, "bounded request body");
    std::cout << "RTSP parser, SDP, response and transport tests PASS\n";
}
