#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

struct ParsedUdpPacket {
    std::string src_ip;
    uint16_t src_port = 0;
    uint16_t dst_port = 0;
    std::vector<uint8_t> payload;
};

// Parses a raw Ethernet frame (as captured via AF_PACKET) down to its UDP
// payload, keeping only IPv4/UDP frames addressed to expected_dst_port.
// Returns std::nullopt for anything else (non-IPv4, non-UDP, wrong port,
// or a frame too short to contain a full header at any layer) rather than
// throwing, since malformed/truncated frames are routine on a live capture
// and must never crash the recorder.
std::optional<ParsedUdpPacket> parseRawEthernetUdp(
    const uint8_t* frame, size_t len, uint16_t expected_dst_port);
