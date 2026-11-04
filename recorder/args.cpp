#include "args.h"

bool parseArgs(int argc, char** argv, Args& args) {
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--out_dir" && i+1 < argc) args.out_dir = argv[++i];
        else if (arg == "--bag_dir" && i+1 < argc) args.bag_dir = argv[++i];
        else if (arg == "--pcap" && i+1 < argc) args.pcap_a_name = argv[++i]; // backward-compatible alias
        else if (arg == "--pcap_a" && i+1 < argc) args.pcap_a_name = argv[++i];
        else if (arg == "--pcap_b" && i+1 < argc) args.pcap_b_name = argv[++i];
        else if (arg == "--bag_a" && i+1 < argc) args.bag_a_name = argv[++i];
        else if (arg == "--bag_b" && i+1 < argc) args.bag_b_name = argv[++i];
        else if (arg == "--port" && i+1 < argc) args.port = std::stoi(argv[++i]);
        else if (arg == "--ip_a" && i+1 < argc) args.ip_a = argv[++i];
        else if (arg == "--ip_b" && i+1 < argc) args.ip_b = argv[++i];
        else if (arg == "--interface" && i+1 < argc) args.interface = argv[++i];
        else if (arg == "--timestamp_source" && i+1 < argc) args.timestamp_source = argv[++i];
        else if (arg == "--enable_bag") args.enable_bag = true;
    }
    return !args.out_dir.empty() && !args.pcap_a_name.empty() && !args.ip_a.empty();
}
