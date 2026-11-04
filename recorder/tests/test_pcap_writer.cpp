#include <catch2/catch_test_macros.hpp>
#include <arpa/inet.h>
#include <cstdio>
#include <cstring>
#include <fstream>
#include "../pcap_writer.h"

namespace {

std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return std::vector<uint8_t>(
        (std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

uint32_t readLE32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

uint16_t readBE16(const uint8_t* p) {
    return static_cast<uint16_t>((p[0] << 8) | p[1]);
}

// Mirrors the internal ipv4Checksum() used by PcapWriter::writePacket, so
// tests can independently confirm the header checksum it writes is correct.
uint16_t ipv4Checksum(const uint8_t* data, size_t len) {
    uint32_t sum = 0;
    for (size_t i = 0; i + 1 < len; i += 2) {
        sum += (static_cast<uint16_t>(data[i]) << 8) | static_cast<uint16_t>(data[i + 1]);
    }
    if (len & 1U) sum += static_cast<uint16_t>(data[len - 1]) << 8;
    while (sum >> 16U) sum = (sum & 0xFFFFU) + (sum >> 16U);
    return static_cast<uint16_t>(~sum);
}

// Removes the backing file when the test (or an early REQUIRE failure)
// leaves scope, so failed runs don't leak files into the working directory.
struct TempFile {
    std::string path;
    explicit TempFile(std::string p) : path(std::move(p)) {}
    ~TempFile() { std::remove(path.c_str()); }
};

} // namespace

TEST_CASE("PcapWriter writes a valid global pcap header", "[pcap_writer]") {
    TempFile tmp("test_pcap_writer_global.pcap");
    { PcapWriter writer(tmp.path); }

    auto bytes = readFile(tmp.path);
    REQUIRE(bytes.size() == 24);
    CHECK(bytes[0] == 0xd4); CHECK(bytes[1] == 0xc3);
    CHECK(bytes[2] == 0xb2); CHECK(bytes[3] == 0xa1); // microsecond magic
    CHECK(readLE32(&bytes[20]) == 1); // network = Ethernet
}

TEST_CASE("PcapWriter::writePacket synthesizes a correct Ethernet/IPv4/UDP frame", "[pcap_writer]") {
    TempFile tmp("test_pcap_writer_packet.pcap");
    std::vector<uint8_t> payload = {1, 2, 3, 4, 5, 6, 7, 8};
    const int64_t ts_ns = 1700000123456789LL;
    {
        PcapWriter writer(tmp.path);
        writer.writePacket(payload, ts_ns, "192.168.1.201", 2368, 2368);
    }

    auto bytes = readFile(tmp.path);
    const size_t record_hdr_off = 24;
    REQUIRE(bytes.size() > record_hdr_off + 16);

    const uint32_t ts_sec = readLE32(&bytes[record_hdr_off]);
    const uint32_t ts_usec = readLE32(&bytes[record_hdr_off + 4]);
    const uint32_t caplen = readLE32(&bytes[record_hdr_off + 8]);
    const uint32_t reclen = readLE32(&bytes[record_hdr_off + 12]);
    CHECK(ts_sec == static_cast<uint32_t>(ts_ns / 1000000000LL));
    CHECK(ts_usec == static_cast<uint32_t>((ts_ns % 1000000000LL) / 1000LL));
    CHECK(caplen == reclen);
    CHECK(caplen == 14 + 20 + 8 + payload.size());
    REQUIRE(bytes.size() == record_hdr_off + 16 + caplen);

    const uint8_t* frame = &bytes[record_hdr_off + 16];
    CHECK(frame[12] == 0x08);
    CHECK(frame[13] == 0x00); // IPv4 ethertype

    const uint8_t* ip = frame + 14;
    CHECK((ip[0] & 0x0F) == 5); // IHL = 5 words = 20 bytes
    CHECK(readBE16(&ip[2]) == 20 + 8 + payload.size());
    CHECK(ip[9] == 17); // UDP
    CHECK(ipv4Checksum(ip, 20) == 0); // a correctly-checksummed header sums to 0
    in_addr expected_src{};
    inet_pton(AF_INET, "192.168.1.201", &expected_src);
    CHECK(std::memcmp(ip + 12, &expected_src.s_addr, 4) == 0);

    const uint8_t* udp = ip + 20;
    CHECK(readBE16(&udp[0]) == 2368); // src port
    CHECK(readBE16(&udp[2]) == 2368); // dst port
    CHECK(readBE16(&udp[4]) == 8 + payload.size());
    CHECK(std::vector<uint8_t>(udp + 8, udp + 8 + payload.size()) == payload);
}

TEST_CASE("PcapWriter::writeRawFrame stores the frame byte-for-byte", "[pcap_writer]") {
    TempFile tmp("test_pcap_writer_raw.pcap");
    std::vector<uint8_t> frame = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x01, 0x02};
    const int64_t ts_ns = 5000000000LL; // 5s, 0us
    {
        PcapWriter writer(tmp.path);
        writer.writeRawFrame(frame.data(), frame.size(), ts_ns);
    }

    auto bytes = readFile(tmp.path);
    REQUIRE(bytes.size() == 24 + 16 + frame.size());
    CHECK(readLE32(&bytes[24]) == 5);
    CHECK(readLE32(&bytes[28]) == 0);
    CHECK(readLE32(&bytes[32]) == frame.size());
    CHECK(readLE32(&bytes[36]) == frame.size());
    CHECK(std::vector<uint8_t>(bytes.begin() + 40, bytes.end()) == frame);
}

TEST_CASE("PcapWriter::writeRawFrame is a no-op for a null or empty frame", "[pcap_writer]") {
    TempFile tmp("test_pcap_writer_noop.pcap");
    {
        PcapWriter writer(tmp.path);
        writer.writeRawFrame(nullptr, 10, 0);
        std::vector<uint8_t> empty;
        writer.writeRawFrame(empty.data(), 0, 0);
    }
    auto bytes = readFile(tmp.path);
    CHECK(bytes.size() == 24); // only the global header was written
}

TEST_CASE("PcapWriter writes multiple packets sequentially", "[pcap_writer]") {
    TempFile tmp("test_pcap_writer_multi.pcap");
    {
        PcapWriter writer(tmp.path);
        writer.writePacket({1, 2, 3}, 1000000000LL, "10.0.0.1", 100, 200);
        writer.writePacket({4, 5}, 2000000000LL, "10.0.0.2", 300, 400);
    }
    auto bytes = readFile(tmp.path);
    const uint32_t first_caplen = readLE32(&bytes[24 + 8]);
    const size_t second_record_off = 24 + 16 + first_caplen;
    REQUIRE(bytes.size() > second_record_off + 16);
    const uint32_t second_caplen = readLE32(&bytes[second_record_off + 8]);
    CHECK(second_caplen == 14 + 20 + 8 + 2);
    CHECK(bytes.size() == second_record_off + 16 + second_caplen);
}
