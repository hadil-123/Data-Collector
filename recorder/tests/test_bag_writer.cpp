#include <catch2/catch_test_macros.hpp>
#include <arpa/inet.h>
#include <cstdio>
#include <cstring>
#include <fstream>
#include "../bag_writer.h"

namespace {

std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return std::vector<uint8_t>(
        (std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

struct TempFile {
    std::string path;
    explicit TempFile(std::string p) : path(std::move(p)) {}
    ~TempFile() { std::remove(path.c_str()); }
};

constexpr size_t kMagicSize = 8;
constexpr size_t kRecordHeaderSize = 8 + 4 + 2 + 2 + 4; // ts_ns + src_ip + src_port + dst_port + len

} // namespace

TEST_CASE("BagWriter writes the LDRBAG01 magic header", "[bag_writer]") {
    TempFile tmp("test_bag_writer_magic.bag");
    { BagWriter writer(tmp.path); }

    auto bytes = readFile(tmp.path);
    REQUIRE(bytes.size() == kMagicSize);
    CHECK(std::memcmp(bytes.data(), "LDRBAG01", 8) == 0);
}

TEST_CASE("BagWriter::writePacket records a packet with the fixed-layout header", "[bag_writer]") {
    TempFile tmp("test_bag_writer_packet.bag");
    std::vector<uint8_t> payload = {10, 20, 30, 40, 50};
    const int64_t ts_ns = 1700000123456789LL;
    {
        BagWriter writer(tmp.path);
        writer.writePacket(payload, ts_ns, "192.168.1.202", 2368, 2369);
    }

    auto bytes = readFile(tmp.path);
    REQUIRE(bytes.size() == kMagicSize + kRecordHeaderSize + payload.size());

    const uint8_t* rec = bytes.data() + kMagicSize;
    int64_t read_ts_ns = 0;
    std::memcpy(&read_ts_ns, rec, sizeof(read_ts_ns));
    CHECK(read_ts_ns == ts_ns);

    uint32_t read_src_ip = 0;
    std::memcpy(&read_src_ip, rec + 8, sizeof(read_src_ip));
    in_addr expected{};
    inet_pton(AF_INET, "192.168.1.202", &expected);
    CHECK(read_src_ip == expected.s_addr);

    uint16_t read_src_port = 0, read_dst_port = 0;
    std::memcpy(&read_src_port, rec + 12, sizeof(read_src_port));
    std::memcpy(&read_dst_port, rec + 14, sizeof(read_dst_port));
    CHECK(read_src_port == 2368);
    CHECK(read_dst_port == 2369);

    uint32_t read_len = 0;
    std::memcpy(&read_len, rec + 16, sizeof(read_len));
    CHECK(read_len == payload.size());

    std::vector<uint8_t> read_payload(bytes.begin() + kMagicSize + kRecordHeaderSize, bytes.end());
    CHECK(read_payload == payload);
}

TEST_CASE("BagWriter::writePacket handles an empty payload", "[bag_writer]") {
    TempFile tmp("test_bag_writer_empty.bag");
    {
        BagWriter writer(tmp.path);
        writer.writePacket({}, 0, "0.0.0.0", 0, 0);
    }
    auto bytes = readFile(tmp.path);
    CHECK(bytes.size() == kMagicSize + kRecordHeaderSize);
    uint32_t read_len = 0;
    std::memcpy(&read_len, bytes.data() + kMagicSize + 16, sizeof(read_len));
    CHECK(read_len == 0);
}

TEST_CASE("BagWriter falls back to INADDR_ANY for an unparseable source IP", "[bag_writer]") {
    TempFile tmp("test_bag_writer_badip.bag");
    {
        BagWriter writer(tmp.path);
        writer.writePacket({1}, 0, "not-an-ip", 1, 2);
    }
    auto bytes = readFile(tmp.path);
    uint32_t read_src_ip = 0;
    std::memcpy(&read_src_ip, bytes.data() + kMagicSize + 8, sizeof(read_src_ip));
    CHECK(read_src_ip == htonl(INADDR_ANY));
}

TEST_CASE("BagWriter writes multiple packets sequentially and each stays self-delimiting", "[bag_writer]") {
    TempFile tmp("test_bag_writer_multi.bag");
    {
        BagWriter writer(tmp.path);
        writer.writePacket({1, 2, 3}, 111, "10.0.0.1", 1, 2);
        writer.writePacket({4, 5}, 222, "10.0.0.2", 3, 4);
    }
    auto bytes = readFile(tmp.path);
    const size_t first_record_off = kMagicSize;
    const size_t second_record_off = first_record_off + kRecordHeaderSize + 3;
    REQUIRE(bytes.size() == second_record_off + kRecordHeaderSize + 2);

    uint32_t second_len = 0;
    std::memcpy(&second_len, bytes.data() + second_record_off + 16, sizeof(second_len));
    CHECK(second_len == 2);
    std::vector<uint8_t> second_payload(
        bytes.begin() + second_record_off + kRecordHeaderSize, bytes.end());
    CHECK(second_payload == std::vector<uint8_t>{4, 5});
}
