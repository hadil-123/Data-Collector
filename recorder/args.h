#pragma once
#include <string>

struct Args {
    std::string out_dir;
    std::string bag_dir;
    std::string pcap_a_name;
    std::string pcap_b_name;
    std::string bag_a_name;
    std::string bag_b_name;
    int port = 2368;
    std::string ip_a, ip_b;
    std::string interface;
    std::string timestamp_source = "kernel";
    bool enable_bag = false;
};

// Parses argv into args. Returns false (and leaves args partially filled)
// if a required option (--out_dir, --pcap_a/--pcap, --ip_a) is missing.
// Pure/side-effect-free besides filling `args`, so it's unit-testable
// without touching sockets or the filesystem.
bool parseArgs(int argc, char** argv, Args& args);
