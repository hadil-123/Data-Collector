#include "bag_writer.h"
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>

namespace {
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

BagWriter::BagWriter(const std::string& path) {
    fd_ = ::open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd_ >= 0) {
        is_open_ = true;
        const char magic[8] = {'L', 'D', 'R', 'B', 'A', 'G', '0', '1'};
        writeAll(fd_, magic, sizeof(magic));
    }
}

BagWriter::~BagWriter() { close(); }

void BagWriter::writePacket(
    const std::vector<uint8_t>& data,
    int64_t ts_ns,
    const std::string& src_ip,
    uint16_t src_port,
    uint16_t dst_port
) {
    if (!is_open_) return;

    in_addr src_addr{};
    if (::inet_pton(AF_INET, src_ip.c_str(), &src_addr) != 1) {
        src_addr.s_addr = htonl(INADDR_ANY);
    }
    const uint32_t src_ip_u32 = src_addr.s_addr;
    const uint32_t payload_len = static_cast<uint32_t>(data.size());

    writeAll(fd_, &ts_ns, sizeof(ts_ns));
    writeAll(fd_, &src_ip_u32, sizeof(src_ip_u32));
    writeAll(fd_, &src_port, sizeof(src_port));
    writeAll(fd_, &dst_port, sizeof(dst_port));
    writeAll(fd_, &payload_len, sizeof(payload_len));
    if (payload_len > 0) {
        writeAll(fd_, data.data(), data.size());
    }
}

void BagWriter::close() {
    if (is_open_) {
        ::close(fd_);
        is_open_ = false;
    }
}
