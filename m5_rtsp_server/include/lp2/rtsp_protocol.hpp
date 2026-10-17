#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace lp2 { namespace rtsp {

struct Request {
    std::string method;
    std::string uri;
    std::string path;
    std::string cseq;
    std::map<std::string, std::string> headers; // lowercase names
};

enum class ParseResult { NeedMore, Complete, Invalid };

// Parses one request from a TCP stream. Limits header to 8192 bytes and
// optional body to 4096 bytes; consumed permits pipelined requests.
ParseResult parse_request(const std::string& input, Request& request,
                          std::size_t& consumed, std::string& error);
bool parse_client_ports(const std::string& transport,
                        std::uint16_t& rtp, std::uint16_t& rtcp);
std::string header(const Request& request, const std::string& lowercase_name);
std::string session_token(const std::string& session_header);
std::string response(unsigned int code, const std::string& phrase,
                     const std::string& cseq,
                     const std::vector<std::pair<std::string, std::string> >& headers,
                     const std::string& body = std::string());
std::string sdp(const std::string& board_ip);

} } // namespace lp2::rtsp
