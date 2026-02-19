#pragma once
#include <string>
#include <vector>
#include <cstdint>

class BagWriter {
public:
    BagWriter(const std::string& path);
    ~BagWriter();
    void writePacket(
        const std::vector<uint8_t>& data,
        int64_t ts_ns,
        const std::string& src_ip,
        uint16_t src_port,
        uint16_t dst_port
    );
    void close();
private:
    int fd_ = -1;
    bool is_open_ = false;
};
