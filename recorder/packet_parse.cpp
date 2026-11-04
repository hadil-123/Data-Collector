#include "packet_parse.h"
#include <arpa/inet.h>
#include <netinet/in.h>

std::optional<ParsedUdpPacket> parseRawEthernetUdp(
    const uint8_t* frame, size_t len, uint16_t expected_dst_port) {
    if (frame == nullptr || len < 14) return std::nullopt;

    const uint16_t ether_type = static_cast<uint16_t>(frame[12] << 8 | frame[13]);
    if (ether_type != 0x0800) return std::nullopt; // IPv4 only

    const size_t ip_offset = 14;
    if (len < ip_offset + 20) return std::nullopt;
    const uint8_t* ip = frame + ip_offset;
    const uint8_t ip_ihl = static_cast<uint8_t>((ip[0] & 0x0F) * 4);
    if (ip_ihl < 20) return std::nullopt;
    if (len < ip_offset + ip_ihl + 8) return std::nullopt;
    if (ip[9] != IPPROTO_UDP) return std::nullopt;

    const uint8_t* udp = ip + ip_ihl;
    const uint16_t src_port = ntohs(*reinterpret_cast<const uint16_t*>(udp));
    const uint16_t dst_port = ntohs(*reinterpret_cast<const uint16_t*>(udp + 2));
    if (dst_port != expected_dst_port) return std::nullopt;

    const uint16_t udp_len = ntohs(*reinterpret_cast<const uint16_t*>(udp + 4));
    if (udp_len < 8) return std::nullopt;
    size_t payload_len = static_cast<size_t>(udp_len - 8);
    const size_t payload_max = len - (ip_offset + ip_ihl + 8);
    if (payload_len > payload_max) payload_len = payload_max;

    char src_ip_buf[INET_ADDRSTRLEN]{};
    inet_ntop(AF_INET, ip + 12, src_ip_buf, sizeof(src_ip_buf));

    ParsedUdpPacket result;
    result.src_ip = src_ip_buf;
    result.src_port = src_port;
    result.dst_port = dst_port;
    const uint8_t* payload_ptr = udp + 8;
    result.payload.assign(payload_ptr, payload_ptr + payload_len);
    return result;
}
