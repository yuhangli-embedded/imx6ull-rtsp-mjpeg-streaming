#include "lp2/rtsp_protocol.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <limits>
#include <sstream>

namespace lp2 { namespace rtsp {
namespace {
std::string lower(std::string value)
{
    for (std::size_t i = 0; i < value.size(); ++i)
        value[i] = static_cast<char>(std::tolower(
            static_cast<unsigned char>(value[i])));
    return value;
}
std::string trim(const std::string& value)
{
    const std::size_t first = value.find_first_not_of(" \t");
    if (first == std::string::npos) return "";
    const std::size_t last = value.find_last_not_of(" \t");
    return value.substr(first, last - first + 1);
}
bool number(const std::string& text, unsigned long& value)
{
    if (text.empty()) return false;
    value = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] < '0' || text[i] > '9') return false;
        const unsigned int digit = static_cast<unsigned int>(text[i] - '0');
        if (value > (std::numeric_limits<unsigned long>::max() - digit) / 10)
            return false;
        value = value * 10 + digit;
    }
    return true;
}
std::string path_from_uri(const std::string& uri)
{
    if (uri == "*") return uri;
    if (uri.compare(0, 1, "/") == 0) return uri;
    if (lower(uri.substr(0, 7)) != "rtsp://") return "";
    const std::size_t slash = uri.find('/', 7);
    if (slash == std::string::npos || slash == 7) return "";
    return uri.substr(slash);
}
}

ParseResult parse_request(const std::string& input, Request& request,
                          std::size_t& consumed, std::string& error)
{
    consumed = 0;
    request = Request();
    const std::size_t end = input.find("\r\n\r\n");
    if (end == std::string::npos) {
        if (input.size() > 8192 || input.find('\0') != std::string::npos) {
            error = "request header exceeds limit or contains NUL";
            return ParseResult::Invalid;
        }
        return ParseResult::NeedMore;
    }
    if (end + 4 > 8192 || input.substr(0, end).find('\0') != std::string::npos) {
        error = "invalid or oversized RTSP header";
        return ParseResult::Invalid;
    }
    const std::size_t first_end = input.find("\r\n");
    if (first_end == std::string::npos || first_end > end) {
        error = "missing RTSP request line"; return ParseResult::Invalid;
    }
    std::istringstream first(input.substr(0, first_end));
    std::string version, extra;
    if (!(first >> request.method >> request.uri >> version) ||
        (first >> extra) || version != "RTSP/1.0" ||
        request.method.empty() || request.uri.empty()) {
        error = "invalid RTSP request line"; return ParseResult::Invalid;
    }
    request.path = path_from_uri(request.uri);
    if (request.path.empty() || request.path.find('?') != std::string::npos ||
        request.path.find('#') != std::string::npos) {
        error = "invalid RTSP request URI"; return ParseResult::Invalid;
    }
    std::size_t pos = first_end + 2;
    unsigned int lines = 0;
    while (pos < end) {
        const std::size_t next = input.find("\r\n", pos);
        if (next == std::string::npos || next > end || ++lines > 64) {
            error = "invalid or excessive RTSP headers";
            return ParseResult::Invalid;
        }
        const std::string line = input.substr(pos, next - pos);
        const std::size_t colon = line.find(':');
        if (colon == std::string::npos || colon == 0 ||
            line[0] == ' ' || line[0] == '\t') {
            error = "malformed RTSP header"; return ParseResult::Invalid;
        }
        const std::string name = lower(trim(line.substr(0, colon)));
        if (name.empty() || request.headers.count(name) != 0) {
            error = "empty or duplicate RTSP header";
            return ParseResult::Invalid;
        }
        request.headers[name] = trim(line.substr(colon + 1));
        pos = next + 2;
    }
    request.cseq = header(request, "cseq");
    unsigned long cseq = 0;
    if (!number(request.cseq, cseq) || cseq > 2147483647UL) {
        error = "missing or invalid CSeq"; return ParseResult::Invalid;
    }
    unsigned long body_length = 0;
    const std::string content_length = header(request, "content-length");
    if (!content_length.empty() &&
        (!number(content_length, body_length) || body_length > 4096)) {
        error = "invalid RTSP Content-Length";
        return ParseResult::Invalid;
    }
    if (input.size() - (end + 4) < body_length) return ParseResult::NeedMore;
    consumed = end + 4 + body_length;
    error.clear();
    return ParseResult::Complete;
}

std::string header(const Request& request, const std::string& lowercase_name)
{
    const std::map<std::string, std::string>::const_iterator it =
        request.headers.find(lowercase_name);
    return it == request.headers.end() ? "" : it->second;
}

std::string session_token(const std::string& session_header)
{
    return trim(session_header.substr(0, session_header.find(';')));
}

bool parse_client_ports(const std::string& transport,
                        std::uint16_t& rtp, std::uint16_t& rtcp)
{
    // Alternatives are comma-separated. Only unicast UDP RTP/AVP is accepted.
    std::size_t begin = 0;
    while (begin < transport.size()) {
        const std::size_t comma = transport.find(',', begin);
        const std::string choice = trim(transport.substr(begin, comma - begin));
        const std::size_t semi = choice.find(';');
        const std::string profile = lower(trim(choice.substr(0, semi)));
        bool unicast = false, bad = false, ports = false;
        unsigned long a = 0, b = 0;
        for (std::size_t pos = semi == std::string::npos ? choice.size() : semi + 1;
             pos < choice.size();) {
            const std::size_t next = choice.find(';', pos);
            const std::string item = lower(trim(choice.substr(pos, next - pos)));
            if (item == "unicast") unicast = true;
            else if (item == "multicast" || item.compare(0, 12, "interleaved=") == 0 ||
                     item.compare(0, 12, "destination=") == 0) bad = true;
            else if (item.compare(0, 12, "client_port=") == 0) {
                const std::string pair = item.substr(12);
                const std::size_t dash = pair.find('-');
                if (ports || dash == std::string::npos ||
                    !number(pair.substr(0, dash), a) ||
                    !number(pair.substr(dash + 1), b)) bad = true;
                ports = true;
            }
            if (next == std::string::npos) break;
            pos = next + 1;
        }
        if ((profile == "rtp/avp" || profile == "rtp/avp/udp") &&
            unicast && ports && !bad && a >= 2 && a <= 65534 &&
            (a % 2) == 0 && b == a + 1) {
            rtp = static_cast<std::uint16_t>(a);
            rtcp = static_cast<std::uint16_t>(b);
            return true;
        }
        if (comma == std::string::npos) break;
        begin = comma + 1;
    }
    return false;
}

std::string response(unsigned int code, const std::string& phrase,
                     const std::string& cseq,
                     const std::vector<std::pair<std::string, std::string> >& headers,
                     const std::string& body)
{
    std::ostringstream out;
    out << "RTSP/1.0 " << code << ' ' << phrase << "\r\n"
        << "CSeq: " << (cseq.empty() ? "0" : cseq) << "\r\n"
        << "Server: LP2-M5.1\r\n";
    for (std::size_t i = 0; i < headers.size(); ++i)
        out << headers[i].first << ": " << headers[i].second << "\r\n";
    out << "Content-Length: " << body.size() << "\r\n\r\n" << body;
    return out.str();
}

std::string sdp(const std::string& board_ip)
{
    return "v=0\r\n"
           "o=- 0 0 IN IP4 " + board_ip + "\r\n"
           "s=LP2 MJPEG Stream\r\n"
           "c=IN IP4 " + board_ip + "\r\n"
           "t=0 0\r\n"
           "a=control:*\r\n"
           "m=video 0 RTP/AVP 26\r\n"
           "a=rtpmap:26 JPEG/90000\r\n"
           "a=control:track1\r\n";
}

} } // namespace lp2::rtsp
