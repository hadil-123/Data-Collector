#include <catch2/catch_test_macros.hpp>
#include "../args.h"

namespace {
// argv must be char* (not const char*) to match the real main(int, char**)
// signature parseArgs is written against.
std::vector<char*> makeArgv(std::vector<std::string>& storage) {
    std::vector<char*> argv;
    for (auto& s : storage) argv.push_back(s.data());
    return argv;
}
}

TEST_CASE("parseArgs accepts the minimal required set", "[args]") {
    std::vector<std::string> storage = {
        "recorder", "--out_dir", "/tmp/out", "--pcap_a", "lidar_A.pcap", "--ip_a", "192.168.1.201",
    };
    auto argv = makeArgv(storage);
    Args args;
    REQUIRE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    CHECK(args.out_dir == "/tmp/out");
    CHECK(args.pcap_a_name == "lidar_A.pcap");
    CHECK(args.ip_a == "192.168.1.201");
    CHECK(args.port == 2368);           // default
    CHECK(args.timestamp_source == "kernel"); // default
    CHECK_FALSE(args.enable_bag);       // default off
}

TEST_CASE("parseArgs rejects missing required fields", "[args]") {
    SECTION("missing --out_dir") {
        std::vector<std::string> storage = {"recorder", "--pcap_a", "a.pcap", "--ip_a", "1.2.3.4"};
        auto argv = makeArgv(storage);
        Args args;
        CHECK_FALSE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    }
    SECTION("missing --pcap_a and --pcap") {
        std::vector<std::string> storage = {"recorder", "--out_dir", "/tmp", "--ip_a", "1.2.3.4"};
        auto argv = makeArgv(storage);
        Args args;
        CHECK_FALSE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    }
    SECTION("missing --ip_a") {
        std::vector<std::string> storage = {"recorder", "--out_dir", "/tmp", "--pcap_a", "a.pcap"};
        auto argv = makeArgv(storage);
        Args args;
        CHECK_FALSE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    }
}

TEST_CASE("parseArgs treats --pcap as a backward-compatible alias for --pcap_a", "[args]") {
    std::vector<std::string> storage = {
        "recorder", "--out_dir", "/tmp", "--pcap", "legacy.pcap", "--ip_a", "1.2.3.4",
    };
    auto argv = makeArgv(storage);
    Args args;
    REQUIRE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    CHECK(args.pcap_a_name == "legacy.pcap");
}

TEST_CASE("parseArgs parses sensor B options and the enable_bag flag", "[args]") {
    std::vector<std::string> storage = {
        "recorder", "--out_dir", "/tmp", "--pcap_a", "A.pcap", "--ip_a", "1.1.1.1",
        "--ip_b", "2.2.2.2", "--pcap_b", "B.pcap", "--bag_dir", "/tmp/bag",
        "--bag_a", "A.bag", "--bag_b", "B.bag", "--enable_bag",
        "--port", "9999", "--interface", "eth0", "--timestamp_source", "system",
    };
    auto argv = makeArgv(storage);
    Args args;
    REQUIRE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    CHECK(args.ip_b == "2.2.2.2");
    CHECK(args.pcap_b_name == "B.pcap");
    CHECK(args.bag_dir == "/tmp/bag");
    CHECK(args.bag_a_name == "A.bag");
    CHECK(args.bag_b_name == "B.bag");
    CHECK(args.enable_bag);
    CHECK(args.port == 9999);
    CHECK(args.interface == "eth0");
    CHECK(args.timestamp_source == "system");
}

TEST_CASE("parseArgs ignores a trailing flag missing its value", "[args]") {
    // "--port" with no following argument must not crash (argv overrun) and
    // must not silently take some other flag's value as the port.
    std::vector<std::string> storage = {
        "recorder", "--out_dir", "/tmp", "--pcap_a", "a.pcap", "--ip_a", "1.2.3.4", "--port",
    };
    auto argv = makeArgv(storage);
    Args args;
    REQUIRE(parseArgs(static_cast<int>(argv.size()), argv.data(), args));
    CHECK(args.port == 2368); // default retained, dangling --port silently ignored
}
