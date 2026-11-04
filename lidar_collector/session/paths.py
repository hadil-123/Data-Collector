"""Filesystem/time helpers used by the session UI: resolving the recorder
binary, formatting sizes/timestamps, and reading progress out of files that
the recorder/pipeline write to while a session is live."""
import os
import time
from datetime import datetime


def resolve_recorder_binary(project_root):
    candidates = [
        os.path.join(project_root, 'recorder', 'recorder'),
        os.path.join(project_root, 'recorder', 'build', 'recorder'),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def now_epoch_ns():
    return time.time_ns()


def fmt_hms_from_ns(epoch_ns):
    return datetime.fromtimestamp(epoch_ns / 1e9).strftime('%H:%M:%S')


def get_file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def get_dir_size(path):
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, _, files in os.walk(path):
        for name in files:
            total += get_file_size(os.path.join(root, name))
    return total


def human_bytes(num):
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(num)
    for unit in units:
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{num} B"


def get_disk_free(path):
    """(free_bytes, total_bytes) for the filesystem holding path, or (None, None)."""
    import shutil
    try:
        probe = path if os.path.isdir(path) else os.path.dirname(path) or "."
        usage = shutil.disk_usage(probe)
        return usage.free, usage.total
    except OSError:
        return None, None


def count_pcap_packets(path):
    """Count complete packet records in a PCAP while it is being written."""
    if not path or not os.path.exists(path):
        return 0
    try:
        with open(path, "rb") as pcap_file:
            header = pcap_file.read(24)
            if len(header) < 24:
                return 0
            packet_count = 0
            while True:
                record_header = pcap_file.read(16)
                if len(record_header) < 16:
                    break
                included_length = int.from_bytes(record_header[8:12], "little")
                if len(pcap_file.read(included_length)) < included_length:
                    break
                packet_count += 1
            return packet_count
    except OSError:
        return 0


def tail_lines(path, n=8):
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip("\n") for l in lines[-n:]]
    except OSError:
        return []


def parse_recorder_counters(log_path):
    import re
    if not log_path or not os.path.exists(log_path):
        return None
    pattern = re.compile(r"pkts total=(\d+)\s+a=(\d+)\s+b=(\d+)\s+dropped_ip=(\d+)")
    last = None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    last = {
                        "total": int(m.group(1)),
                        "a": int(m.group(2)),
                        "b": int(m.group(3)),
                        "dropped": int(m.group(4)),
                    }
    except OSError:
        return None
    return last
