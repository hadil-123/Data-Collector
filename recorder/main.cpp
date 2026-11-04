#include "pcap_writer.h"
#include "bag_writer.h"
#include "args.h"
#include "packet_parse.h"
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/time.h>
#include <linux/if_packet.h>
#include <linux/if_ether.h>
#include <linux/sockios.h>
#include <linux/net_tstamp.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <netinet/ip.h>
#include <netinet/udp.h>
#include <unistd.h>
#include <cstring>
#include <iostream>
#include <vector>
#include <string>
#include <memory>
#include <cerrno>

int main(int argc, char** argv) {
    std::cout.setf(std::ios::unitbuf);
    std::cerr.setf(std::ios::unitbuf);

    Args args;
    if (!parseArgs(argc, argv, args)) {
        std::cerr << "Usage: ./recorder record --out_dir DIR [--bag_dir DIR] --pcap_a FILE [--pcap_b FILE] [--bag_a FILE] [--bag_b FILE] --port 2368 --ip_a IP [--ip_b IP] [--interface IFACE] [--timestamp_source kernel|system] [--enable_bag]\n";
        return 1;
    }
    if (args.bag_dir.empty()) {
        args.bag_dir = args.out_dir;
    }
    const bool has_sensor_b = !args.ip_b.empty();
    if (has_sensor_b && args.pcap_b_name.empty()) {
        args.pcap_b_name = "lidar_B.pcap";
    }
    if (args.bag_a_name.empty()) {
        args.bag_a_name = "lidar_A.bag";
    }
    if (has_sensor_b && args.bag_b_name.empty()) {
        args.bag_b_name = "lidar_B.bag";
    }

    std::string pcap_a_path = args.out_dir + "/" + args.pcap_a_name;
    PcapWriter writer_a(pcap_a_path);
    std::unique_ptr<BagWriter> bag_writer_a;
    if (args.enable_bag) {
        bag_writer_a = std::make_unique<BagWriter>(args.bag_dir + "/" + args.bag_a_name);
    }
    std::unique_ptr<PcapWriter> writer_b;
    std::unique_ptr<BagWriter> bag_writer_b;
    if (has_sensor_b) {
        std::string pcap_b_path = args.out_dir + "/" + args.pcap_b_name;
        writer_b = std::make_unique<PcapWriter>(pcap_b_path);
        if (args.enable_bag) {
            bag_writer_b = std::make_unique<BagWriter>(args.bag_dir + "/" + args.bag_b_name);
        }
    }
    
    uint64_t total_packets = 0;
    uint64_t packets_a = 0;
    uint64_t packets_b = 0;
    uint64_t dropped_ip = 0;
    uint64_t timeout_ticks = 0;
    auto now_system_ns = []() -> int64_t {
        timeval tv{};
        gettimeofday(&tv, nullptr);
        return int64_t(tv.tv_sec) * 1000000000LL + tv.tv_usec * 1000LL;
    };
    auto extract_ts_ns = [&](msghdr* msg) -> int64_t {
        if (args.timestamp_source != "kernel" || msg == nullptr) {
            return now_system_ns();
        }
        for (cmsghdr* cmsg = CMSG_FIRSTHDR(msg); cmsg; cmsg = CMSG_NXTHDR(msg, cmsg)) {
            if (cmsg->cmsg_level == SOL_SOCKET && cmsg->cmsg_type == SO_TIMESTAMPNS) {
                const timespec* ts = reinterpret_cast<const timespec*>(CMSG_DATA(cmsg));
                return int64_t(ts->tv_sec) * 1000000000LL + ts->tv_nsec;
            }
        }
        return now_system_ns();
    };
    auto handle_packet = [&](const std::vector<uint8_t>& payload,
                             const std::string& src_ip,
                             uint16_t src_port,
                             uint16_t dst_port,
                             int64_t ts_ns,
                             const uint8_t* raw_frame,
                             size_t raw_frame_len) {
        ++total_packets;
        if (total_packets == 1) {
            std::cerr << "[recorder] first packet src=" << src_ip
                      << ":" << src_port << " len=" << payload.size() << "\n";
        }
        if (src_ip == args.ip_a) {
            if (raw_frame && raw_frame_len > 0) {
                writer_a.writeRawFrame(raw_frame, raw_frame_len, ts_ns);
            } else {
                writer_a.writePacket(payload, ts_ns, src_ip, src_port, dst_port);
            }
            if (bag_writer_a) {
                bag_writer_a->writePacket(payload, ts_ns, src_ip, src_port, dst_port);
            }
            ++packets_a;
        } else if (has_sensor_b && src_ip == args.ip_b && writer_b) {
            if (raw_frame && raw_frame_len > 0) {
                writer_b->writeRawFrame(raw_frame, raw_frame_len, ts_ns);
            } else {
                writer_b->writePacket(payload, ts_ns, src_ip, src_port, dst_port);
            }
            if (bag_writer_b) {
                bag_writer_b->writePacket(payload, ts_ns, src_ip, src_port, dst_port);
            }
            ++packets_b;
        } else {
            ++dropped_ip;
            if (dropped_ip <= 5) {
                std::cerr << "[recorder] ignored src_ip=" << src_ip
                          << " expected A=" << args.ip_a
                          << (has_sensor_b ? (" B=" + args.ip_b) : "") << "\n";
            }
        }
        if ((total_packets % 1000ULL) == 0ULL) {
            std::cerr << "[recorder] pkts total=" << total_packets
                      << " a=" << packets_a
                      << " b=" << packets_b
                      << " dropped_ip=" << dropped_ip << "\n";
        }
    };

    int sockfd = -1;
    bool raw_packet_mode = false;
    if (!args.interface.empty()) {
        const unsigned int ifindex = if_nametoindex(args.interface.c_str());
        if (ifindex == 0) {
            std::cerr << "[recorder] warning: interface " << args.interface
                      << " not found, fallback to UDP socket mode\n";
        } else {
            sockfd = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_IP));
            if (sockfd >= 0) {
                sockaddr_ll sll{};
                sll.sll_family = AF_PACKET;
                sll.sll_ifindex = static_cast<int>(ifindex);
                sll.sll_protocol = htons(ETH_P_IP);
                if (bind(sockfd, reinterpret_cast<sockaddr*>(&sll), sizeof(sll)) == 0) {
                    raw_packet_mode = true;
                } else {
                    perror("bind(AF_PACKET)");
                    close(sockfd);
                    sockfd = -1;
                }
            } else {
                perror("socket(AF_PACKET)");
            }
        }
    }

    if (!raw_packet_mode) {
        sockfd = socket(AF_INET, SOCK_DGRAM, 0);
        if (sockfd < 0) { perror("socket(AF_INET)"); return 1; }
        if (!args.interface.empty()) {
            if (setsockopt(sockfd, SOL_SOCKET, SO_BINDTODEVICE, args.interface.c_str(), args.interface.size() + 1) < 0) {
                perror("setsockopt(SO_BINDTODEVICE)");
                close(sockfd);
                return 1;
            }
        }
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(args.port);
        addr.sin_addr.s_addr = INADDR_ANY;
        if (bind(sockfd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
            perror("bind(AF_INET)");
            close(sockfd);
            return 1;
        }
    }

    // Kernel default (net.core.rmem_default, often ~208KB) is too small to absorb
    // receive bursts on a jittery link (e.g. Wi-Fi power-save wake cycles), causing
    // silent packet drops below the application (invisible to dropped_ip). Request a
    // larger buffer; the kernel silently caps this at net.core.rmem_max if exceeded.
    {
        int rcvbuf = 8 * 1024 * 1024;
        if (setsockopt(sockfd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf)) < 0) {
            perror("setsockopt(SO_RCVBUF)");
        }
    }

    if (args.timestamp_source == "kernel") {
        int val = 1;
        setsockopt(sockfd, SOL_SOCKET, SO_TIMESTAMPNS, &val, sizeof(val));
    }
    timeval rcv_timeout{};
    rcv_timeout.tv_sec = 1;
    rcv_timeout.tv_usec = 0;
    setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, &rcv_timeout, sizeof(rcv_timeout));

    if (raw_packet_mode) {
        std::cout << "[recorder] Capture mode: raw Ethernet (pcap-equivalent)\n";
    } else {
        std::cout << "[recorder] Capture mode: UDP payload fallback (non-raw)\n";
    }
    std::cout << "[recorder] Listening on UDP port " << args.port;
    if (!args.interface.empty()) {
        std::cout << " on interface " << args.interface;
    }
    std::cout << "\n";
    std::cout << "[recorder] Filtering source IPs: A=" << args.ip_a;
    if (has_sensor_b) {
        std::cout << ", B=" << args.ip_b;
    }
    std::cout << "\n";

    while (true) {
        uint8_t buf[65536];
        sockaddr_storage src_addr{};
        socklen_t addrlen = sizeof(src_addr);
        msghdr msg{};
        iovec iov{buf, sizeof(buf)};
        char ctrl[1024];
        msg.msg_name = &src_addr;
        msg.msg_namelen = addrlen;
        msg.msg_iov = &iov;
        msg.msg_iovlen = 1;
        msg.msg_control = ctrl;
        msg.msg_controllen = sizeof(ctrl);

        const ssize_t len = recvmsg(sockfd, &msg, 0);
        if (len <= 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                ++timeout_ticks;
                if ((timeout_ticks % 2ULL) == 0ULL) {
                    std::cerr << "[recorder] idle: no UDP received yet"
                              << " total=" << total_packets
                              << " a=" << packets_a
                              << " b=" << packets_b
                              << " dropped_ip=" << dropped_ip << "\n";
                }
                continue;
            }
            perror("recvmsg");
            continue;
        }
        const int64_t ts_ns = extract_ts_ns(&msg);

        if (raw_packet_mode) {
            const auto parsed = parseRawEthernetUdp(buf, static_cast<size_t>(len), static_cast<uint16_t>(args.port));
            if (!parsed) continue;
            handle_packet(parsed->payload, parsed->src_ip, parsed->src_port, parsed->dst_port,
                          ts_ns, buf, static_cast<size_t>(len));
        } else {
            sockaddr_in* udp_src = reinterpret_cast<sockaddr_in*>(&src_addr);
            const std::string src_ip = inet_ntoa(udp_src->sin_addr);
            const uint16_t src_port = ntohs(udp_src->sin_port);
            std::vector<uint8_t> payload(buf, buf + len);
            handle_packet(payload, src_ip, src_port, static_cast<uint16_t>(args.port), ts_ns, nullptr, 0);
        }
    }
}
