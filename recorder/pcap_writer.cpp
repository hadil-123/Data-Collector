#include "pcap_writer.h"
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>
#include <sys/stat.h>
#include <iostream>

namespace {
uint16_t ipv4Checksum(const uint8_t* data, size_t len) {
    uint32_t sum = 0;
    for (size_t i = 0; i + 1 < len; i += 2) {
        uint16_t word = (uint16_t(data[i]) << 8) | uint16_t(data[i + 1]);
        sum += word;
    }
    if (len & 1U) {
        sum += uint16_t(data[len - 1]) << 8;
    }
    while (sum >> 16U) {
        sum = (sum & 0xFFFFU) + (sum >> 16U);
    }
    return uint16_t(~sum);
}

bool writeAll(int fd, const void* data, size_t size) {
    const uint8_t* p = static_cast<const uint8_t*>(data);
    size_t total = 0;
    while (total < size) {
        const ssize_t n = ::write(fd, p + total, size - total);
        if (n <= 0) {
            return false;
        }
        total += static_cast<size_t>(n);
    }
    return true;
}
} // namespace

PcapWriter::PcapWriter(const std::string& path) {
    fd_ = ::open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd_ >= 0) {
        is_open_ = true;
        // PCAP global header (little endian, microsecond resolution).
        // This is broadly compatible with older libpcap builds used by some tools.
        uint8_t hdr[24] = {
            0xd4, 0xc3, 0xb2, 0xa1, // microsecond magic
            0x02, 0x00, 0x04, 0x00, // version
            0x00, 0x00, 0x00, 0x00, // thiszone
            0x00, 0x00, 0x00, 0x00, // sigfigs
            0xff, 0xff, 0x00, 0x00, // snaplen
            0x01, 0x00, 0x00, 0x00  // network (Ethernet)
        };
        writeAll(fd_, hdr, sizeof(hdr));
    }
}

PcapWriter::~PcapWriter() { close(); }

void PcapWriter::writeRawFrame(const uint8_t* frame, size_t frame_len, int64_t kernel_ts_ns) {
    if (!is_open_ || frame == nullptr || frame_len == 0) return;
    uint32_t ts_sec = uint32_t(kernel_ts_ns / 1000000000LL);
    uint32_t ts_usec = uint32_t((kernel_ts_ns % 1000000000LL) / 1000LL);
    uint32_t caplen = static_cast<uint32_t>(frame_len);
    uint32_t len = static_cast<uint32_t>(frame_len);
    writeAll(fd_, &ts_sec, sizeof(ts_sec));
    writeAll(fd_, &ts_usec, sizeof(ts_usec));
    writeAll(fd_, &caplen, sizeof(caplen));
    writeAll(fd_, &len, sizeof(len));
    writeAll(fd_, frame, frame_len);
}

void PcapWriter::writePacket(
    const std::vector<uint8_t>& data,
    int64_t kernel_ts_ns,
    const std::string& src_ip,
    uint16_t src_port,
    uint16_t dst_port
) {
    if (!is_open_) return;

    const uint16_t ip_len = static_cast<uint16_t>(20 + 8 + data.size());
    const uint16_t udp_len = static_cast<uint16_t>(8 + data.size());
    std::vector<uint8_t> frame(14 + ip_len, 0);

    // Ethernet header
    std::memset(frame.data(), 0xff, 6);      // dst MAC (broadcast placeholder)
    std::memset(frame.data() + 6, 0x00, 6);  // src MAC placeholder
    frame[12] = 0x08;
    frame[13] = 0x00; // IPv4

    // IPv4 header
    uint8_t* ip = frame.data() + 14;
    ip[0] = 0x45; // version + ihl
    ip[1] = 0x00; // dscp/ecn
    ip[2] = static_cast<uint8_t>((ip_len >> 8) & 0xFF);
    ip[3] = static_cast<uint8_t>(ip_len & 0xFF);
    ip[4] = 0x00;
    ip[5] = 0x00;
    ip[6] = 0x00;
    ip[7] = 0x00;
    ip[8] = 64;   // ttl
    ip[9] = 17;   // UDP
    ip[10] = 0x00;
    ip[11] = 0x00;

    in_addr src_addr{};
    if (::inet_pton(AF_INET, src_ip.c_str(), &src_addr) != 1) {
        src_addr.s_addr = htonl(INADDR_ANY);
    }
    in_addr dst_addr{};
    dst_addr.s_addr = htonl(INADDR_BROADCAST);
    std::memcpy(ip + 12, &src_addr.s_addr, 4);
    std::memcpy(ip + 16, &dst_addr.s_addr, 4);
    const uint16_t ip_csum = ipv4Checksum(ip, 20);
    ip[10] = static_cast<uint8_t>((ip_csum >> 8) & 0xFF);
    ip[11] = static_cast<uint8_t>(ip_csum & 0xFF);

    // UDP header
    uint8_t* udp = ip + 20;
    udp[0] = static_cast<uint8_t>((src_port >> 8) & 0xFF);
    udp[1] = static_cast<uint8_t>(src_port & 0xFF);
    udp[2] = static_cast<uint8_t>((dst_port >> 8) & 0xFF);
    udp[3] = static_cast<uint8_t>(dst_port & 0xFF);
    udp[4] = static_cast<uint8_t>((udp_len >> 8) & 0xFF);
    udp[5] = static_cast<uint8_t>(udp_len & 0xFF);
    udp[6] = 0x00;
    udp[7] = 0x00; // checksum optional for IPv4

    std::memcpy(udp + 8, data.data(), data.size());

    uint32_t ts_sec = uint32_t(kernel_ts_ns / 1000000000LL);
    uint32_t ts_usec = uint32_t((kernel_ts_ns % 1000000000LL) / 1000LL);
    uint32_t caplen = frame.size();
    uint32_t len = frame.size();
    writeAll(fd_, &ts_sec, sizeof(ts_sec));
    writeAll(fd_, &ts_usec, sizeof(ts_usec));
    writeAll(fd_, &caplen, sizeof(caplen));
    writeAll(fd_, &len, sizeof(len));
    writeAll(fd_, frame.data(), frame.size());
}

void PcapWriter::close() {
    if (is_open_) {
        ::close(fd_);
        is_open_ = false;
    }
}
