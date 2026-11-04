#include <catch2/catch_test_macros.hpp>
#include <arpa/inet.h>
#include "../packet_parse.h"

namespace {

// Builds a well-formed Ethernet(IPv4/UDP) frame carrying `payload`, destined
// to `dst_port`. Mirrors PcapWriter::writePacket's own frame construction,
// so these tests exercise the exact wire format the recorder produces
// (and, symmetrically, must be able to parse back out of a raw capture).
std::vector<uint8_t> buildUdpFrame(
    const std::string& src_ip, uint16_t src_port, uint16_t dst_port,
    const std::vector<uint8_t>& payload) {
    const uint16_t udp_len = static_cast<uint16_t>(8 + payload.size());
    const uint16_t ip_len = static_cast<uint16_t>(20 + udp_len);
    std::vector<uint8_t> frame(14 + ip_len, 0);

    frame[12] = 0x08;
    frame[13] = 0x00; // IPv4

    uint8_t* ip = frame.data() + 14;
    ip[0] = 0x45; // version 4, IHL=5 (20 bytes)
    ip[2] = static_cast<uint8_t>((ip_len >> 8) & 0xFF);
    ip[3] = static_cast<uint8_t>(ip_len & 0xFF);
    ip[9] = 17; // UDP
    in_addr addr{};
    inet_pton(AF_INET, src_ip.c_str(), &addr);
    std::memcpy(ip + 12, &addr.s_addr, 4);

    uint8_t* udp = ip + 20;
    udp[0] = static_cast<uint8_t>((src_port >> 8) & 0xFF);
    udp[1] = static_cast<uint8_t>(src_port & 0xFF);
    udp[2] = static_cast<uint8_t>((dst_port >> 8) & 0xFF);
    udp[3] = static_cast<uint8_t>(dst_port & 0xFF);
    udp[4] = static_cast<uint8_t>((udp_len >> 8) & 0xFF);
    udp[5] = static_cast<uint8_t>(udp_len & 0xFF);
    std::memcpy(udp + 8, payload.data(), payload.size());

    return frame;
}

} // namespace

TEST_CASE("parseRawEthernetUdp extracts a well-formed UDP/IPv4 frame", "[packet_parse]") {
    std::vector<uint8_t> payload = {0xDE, 0xAD, 0xBE, 0xEF};
    auto frame = buildUdpFrame("192.168.1.201", 2368, 2368, payload);

    auto parsed = parseRawEthernetUdp(frame.data(), frame.size(), 2368);
    REQUIRE(parsed.has_value());
    CHECK(parsed->src_ip == "192.168.1.201");
    CHECK(parsed->src_port == 2368);
    CHECK(parsed->dst_port == 2368);
    CHECK(parsed->payload == payload);
}

TEST_CASE("parseRawEthernetUdp rejects frames to the wrong destination port", "[packet_parse]") {
    auto frame = buildUdpFrame("10.0.0.1", 5000, 1234, {1, 2, 3});
    auto parsed = parseRawEthernetUdp(frame.data(), frame.size(), /*expected_dst_port=*/2368);
    CHECK_FALSE(parsed.has_value());
}

TEST_CASE("parseRawEthernetUdp rejects non-IPv4 ethertypes", "[packet_parse]") {
    auto frame = buildUdpFrame("10.0.0.1", 5000, 2368, {1, 2, 3});
    frame[12] = 0x86; frame[13] = 0xDD; // IPv6 ethertype — not supported
    auto parsed = parseRawEthernetUdp(frame.data(), frame.size(), 2368);
    CHECK_FALSE(parsed.has_value());
}

TEST_CASE("parseRawEthernetUdp rejects non-UDP IP protocols", "[packet_parse]") {
    auto frame = buildUdpFrame("10.0.0.1", 5000, 2368, {1, 2, 3});
    frame[14 + 9] = 6; // TCP instead of UDP(17)
    auto parsed = parseRawEthernetUdp(frame.data(), frame.size(), 2368);
    CHECK_FALSE(parsed.has_value());
}

TEST_CASE("parseRawEthernetUdp rejects frames too short to hold any header", "[packet_parse]") {
    std::vector<uint8_t> tiny = {1, 2, 3};
    CHECK_FALSE(parseRawEthernetUdp(tiny.data(), tiny.size(), 2368).has_value());
    CHECK_FALSE(parseRawEthernetUdp(nullptr, 100, 2368).has_value());
}

TEST_CASE("parseRawEthernetUdp rejects a frame truncated inside the IP header", "[packet_parse]") {
    auto frame = buildUdpFrame("10.0.0.1", 5000, 2368, {1, 2, 3, 4, 5});
    frame.resize(14 + 10); // only 10 of the 20 IP header bytes survive
    CHECK_FALSE(parseRawEthernetUdp(frame.data(), frame.size(), 2368).has_value());
}

TEST_CASE("parseRawEthernetUdp rejects a frame truncated inside the UDP header", "[packet_parse]") {
    auto frame = buildUdpFrame("10.0.0.1", 5000, 2368, {1, 2, 3, 4, 5});
    frame.resize(14 + 20 + 4); // only 4 of the 8 UDP header bytes survive
    CHECK_FALSE(parseRawEthernetUdp(frame.data(), frame.size(), 2368).has_value());
}

TEST_CASE("parseRawEthernetUdp clamps payload to what's actually captured", "[packet_parse]") {
    // The UDP header claims a longer payload than the physical frame
    // actually carries (e.g. the kernel truncated capture to a snaplen) —
    // must not read/copy past the end of the buffer.
    std::vector<uint8_t> payload(100, 0x7A);
    auto frame = buildUdpFrame("10.0.0.1", 5000, 2368, payload);
    frame.resize(frame.size() - 50); // physically chop off the last 50 bytes
    auto parsed = parseRawEthernetUdp(frame.data(), frame.size(), 2368);
    REQUIRE(parsed.has_value());
    CHECK(parsed->payload.size() == 50);
}

TEST_CASE("parseRawEthernetUdp honors a non-default IHL (IP options present)", "[packet_parse]") {
    auto frame = buildUdpFrame("10.0.0.1", 5000, 2368, {9, 9, 9});
    // Bump IHL from 5 (20 bytes) to 6 (24 bytes) with 4 bytes of (junk)
    // options inserted — if the parser ignored IHL and assumed a fixed
    // 20-byte IP header, it would misread the UDP header entirely.
    std::vector<uint8_t> with_options(frame.begin(), frame.begin() + 14 + 20);
    with_options[14] = 0x46; // version 4, IHL=6
    with_options.insert(with_options.begin() + 14 + 20, {0, 0, 0, 0});
    with_options.insert(with_options.end(), frame.begin() + 14 + 20, frame.end());
    auto parsed = parseRawEthernetUdp(with_options.data(), with_options.size(), 2368);
    REQUIRE(parsed.has_value());
    CHECK(parsed->payload == std::vector<uint8_t>{9, 9, 9});
}
