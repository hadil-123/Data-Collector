import os
import struct
import time

from lidar_collector.session import paths


def test_resolve_recorder_binary_prefers_top_level(tmp_path):
    top = tmp_path / "recorder" / "recorder"
    build = tmp_path / "recorder" / "build" / "recorder"
    build.parent.mkdir(parents=True)
    build.write_text("x")
    build.chmod(0o755)
    top.write_text("x")
    top.chmod(0o755)
    assert paths.resolve_recorder_binary(str(tmp_path)) == str(top)


def test_resolve_recorder_binary_falls_back_to_build(tmp_path):
    build = tmp_path / "recorder" / "build" / "recorder"
    build.parent.mkdir(parents=True)
    build.write_text("x")
    build.chmod(0o755)
    assert paths.resolve_recorder_binary(str(tmp_path)) == str(build)


def test_resolve_recorder_binary_none_when_missing(tmp_path):
    assert paths.resolve_recorder_binary(str(tmp_path)) is None


def test_resolve_recorder_binary_ignores_non_executable(tmp_path):
    top = tmp_path / "recorder" / "recorder"
    top.parent.mkdir(parents=True)
    top.write_text("x")
    top.chmod(0o644)
    assert paths.resolve_recorder_binary(str(tmp_path)) is None


def test_now_epoch_ns_is_close_to_wall_clock():
    assert abs(paths.now_epoch_ns() - time.time_ns()) < 5_000_000_000


def test_fmt_hms_from_ns():
    # 1970-01-01T00:00:00 local epoch start isn't portable across timezones,
    # so just check the format shape instead of a fixed string.
    s = paths.fmt_hms_from_ns(paths.now_epoch_ns())
    assert len(s) == 8 and s[2] == ':' and s[5] == ':'


def test_get_file_size(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x" * 37)
    assert paths.get_file_size(str(f)) == 37


def test_get_file_size_missing():
    assert paths.get_file_size("/nonexistent/path/xyz") == 0


def test_get_dir_size(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"x" * 5)
    assert paths.get_dir_size(str(tmp_path)) == 15


def test_get_dir_size_missing():
    assert paths.get_dir_size("/nonexistent/path/xyz") == 0
    assert paths.get_dir_size(None) == 0


def test_human_bytes():
    assert paths.human_bytes(0) == "0.0 B"
    assert paths.human_bytes(1023) == "1023.0 B"
    assert paths.human_bytes(1024) == "1.0 KB"
    assert paths.human_bytes(1024 * 1024) == "1.0 MB"
    assert paths.human_bytes(1024 ** 4) == "1.0 TB"


def test_get_disk_free(tmp_path):
    free, total = paths.get_disk_free(str(tmp_path))
    assert free is not None and total is not None
    assert 0 < free <= total


def _write_pcap(path, n_packets):
    with open(path, "wb") as f:
        f.write(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)  # 24-byte global header
        for _ in range(n_packets):
            payload = b"\x01" * 10
            f.write(struct.pack("<IIII", 0, 0, len(payload), len(payload)))
            f.write(payload)


def test_count_pcap_packets(tmp_path):
    p = tmp_path / "x.pcap"
    _write_pcap(str(p), 3)
    assert paths.count_pcap_packets(str(p)) == 3


def test_count_pcap_packets_missing_or_truncated(tmp_path):
    assert paths.count_pcap_packets(str(tmp_path / "nope.pcap")) == 0
    short = tmp_path / "short.pcap"
    short.write_bytes(b"\xd4\xc3\xb2\xa1")  # shorter than 24-byte header
    assert paths.count_pcap_packets(str(short)) == 0


def test_tail_lines(tmp_path):
    p = tmp_path / "log.txt"
    p.write_text("\n".join(f"line{i}" for i in range(20)) + "\n")
    assert paths.tail_lines(str(p), n=3) == ["line17", "line18", "line19"]


def test_tail_lines_missing():
    assert paths.tail_lines(None) == []
    assert paths.tail_lines("/nonexistent/path") == []


def test_parse_recorder_counters(tmp_path):
    p = tmp_path / "recorder.log"
    p.write_text(
        "starting up\n"
        "pkts total=100 a=60 b=40 dropped_ip=0\n"
        "pkts total=250 a=150 b=100 dropped_ip=2\n"
    )
    counters = paths.parse_recorder_counters(str(p))
    assert counters == {"total": 250, "a": 150, "b": 100, "dropped": 2}


def test_parse_recorder_counters_missing():
    assert paths.parse_recorder_counters(None) is None
    assert paths.parse_recorder_counters("/nonexistent/path") is None


def test_parse_recorder_counters_no_match(tmp_path):
    p = tmp_path / "recorder.log"
    p.write_text("nothing matching here\n")
    assert paths.parse_recorder_counters(str(p)) is None
