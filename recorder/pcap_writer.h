#pragma once
#include <string>
#include <vector>
#include <cstdint>

class PcapWriter {
public:
    PcapWriter(const std::string& path);
    ~PcapWriter();
    void writeRawFrame(const uint8_t* frame, size_t frame_len, int64_t kernel_ts_ns);
    void writePacket(
        const std::vector<uint8_t>& data,
        int64_t kernel_ts_ns,
        const std::string& src_ip,
        uint16_t src_port,
        uint16_t dst_port
    );
    void close();
private:
    int fd_ = -1;
    bool is_open_ = false;
};
