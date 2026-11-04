import os
import numpy as np
import pytest

import pcap_to_pcd as p2p


def test_write_pcd_binary_round_trip(tmp_path):
    pts = np.array([
        [1.0, 2.0, 3.0, 50.0, 0.0, 0.0, 0.0, 0.0],
        [-1.5, 0.25, 9.0, 120.0, 0.1, 1.0, 5.0, 1.0],
    ], dtype="<f4")
    out = tmp_path / "frame.pcd"
    p2p.write_pcd_binary(str(out), pts)

    content = out.read_bytes()
    assert content.startswith(b"# .PCD v0.7")
    assert b"FIELDS x y z intensity time column ring return_type" in content
    assert b"POINTS 2" in content
    assert b"DATA binary" in content

    # Read back via the shared play_pcd_sequence reader to confirm the two
    # scripts' PCD readers/writers stay compatible with each other.
    import play_pcd_sequence as pps
    arr = pps.read_pcd_binary(str(out))
    assert arr.shape[0] == 2
    np.testing.assert_allclose(arr["x"], [1.0, -1.5], atol=1e-5)
    np.testing.assert_allclose(arr["intensity"], [50.0, 120.0], atol=1e-5)
    np.testing.assert_allclose(arr["ring"], [0.0, 5.0], atol=1e-5)


def test_write_pcd_binary_empty():
    pts = np.zeros((0, 8), dtype="<f4")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pcd", delete=False) as f:
        path = f.name
    try:
        p2p.write_pcd_binary(path, pts)
        with open(path, "rb") as f:
            content = f.read()
        assert b"POINTS 0" in content
        assert b"WIDTH 0" in content
    finally:
        os.remove(path)


def _write_scenario_csv(path, rows):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event", "hh:mm:ss", "elapsed_sec", "epoch_ns", "scenario_id",
                    "scenario_label", "zone", "num_people", "occlusion", "notes", "status"])
        for row in rows:
            w.writerow(row)


def test_load_scenario_intervals_pairs_start_end(tmp_path):
    csv_path = tmp_path / "log.csv"
    _write_scenario_csv(csv_path, [
        ["scenario_start", "10:00:00", "0", "1000", "D1", "Routine", "", 1, "none", "", "ok"],
        ["scenario_end", "10:00:10", "10", "2000", "D1", "Routine", "", 1, "none", "", "ok"],
        ["scenario_start", "10:01:00", "60", "3000", "A1", "Entrer", "", 1, "none", "", "ok"],
        ["scenario_end", "10:01:05", "65", "4000", "A1", "Entrer", "", 1, "none", "", "ok"],
    ])
    intervals = p2p.load_scenario_intervals(str(csv_path))
    assert intervals == [(1000, 2000, "D1"), (3000, 4000, "A1")]


def test_load_scenario_intervals_multiple_takes_same_id(tmp_path):
    csv_path = tmp_path / "log.csv"
    _write_scenario_csv(csv_path, [
        ["scenario_start", "10:00:00", "0", "100", "A1", "Entrer", "", 1, "none", "", "ok"],
        ["scenario_end", "10:00:05", "5", "200", "A1", "Entrer", "", 1, "none", "", "ok"],
        ["scenario_start", "10:02:00", "120", "300", "A1", "Entrer", "", 1, "none", "", "ok"],
        ["scenario_end", "10:02:05", "125", "400", "A1", "Entrer", "", 1, "none", "", "ok"],
    ])
    intervals = p2p.load_scenario_intervals(str(csv_path))
    assert len(intervals) == 2
    assert all(iv[2] == "A1" for iv in intervals)
    assert intervals[0][0] < intervals[1][0]


def test_load_scenario_intervals_unmatched_start_is_dropped(tmp_path):
    csv_path = tmp_path / "log.csv"
    _write_scenario_csv(csv_path, [
        ["scenario_start", "10:00:00", "0", "100", "A1", "Entrer", "", 1, "none", "", "ok"],
        # no matching scenario_end for A1 — session aborted mid-scenario
    ])
    intervals = p2p.load_scenario_intervals(str(csv_path))
    assert intervals == []


def test_scenario_for_ts_inside_and_outside_interval():
    intervals = [(100, 200, "D1"), (300, 400, "A1")]
    assert p2p.scenario_for_ts(intervals, 150) == "D1"
    assert p2p.scenario_for_ts(intervals, 100) == "D1"  # inclusive lower bound
    assert p2p.scenario_for_ts(intervals, 200) == "D1"  # inclusive upper bound
    assert p2p.scenario_for_ts(intervals, 350) == "A1"
    assert p2p.scenario_for_ts(intervals, 250) == ""  # gap between intervals
    assert p2p.scenario_for_ts(intervals, 50) == ""   # before everything


def test_extract_scenario_pcap_trims_to_time_range(tmp_path):
    dpkt = pytest.importorskip("dpkt")
    src = tmp_path / "full.pcap"
    with open(src, "wb") as f:
        writer = dpkt.pcap.Writer(f, linktype=1)
        for i, ts in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
            writer.writepkt(bytes([i]) * 10, ts=ts)

    out = tmp_path / "trimmed.pcap"
    n = p2p.extract_scenario_pcap(str(src), str(out), start_ns=int(2.0e9), end_ns=int(4.0e9))
    assert n == 3  # ts=2.0, 3.0, 4.0 inclusive

    with open(out, "rb") as f:
        reader = dpkt.pcap.Reader(f)
        kept = [ts for ts, _ in reader]
    assert kept == pytest.approx([2.0, 3.0, 4.0])


def test_extract_scenario_pcap_handles_truncated_trailing_record(tmp_path):
    dpkt = pytest.importorskip("dpkt")
    src = tmp_path / "truncated.pcap"
    with open(src, "wb") as f:
        writer = dpkt.pcap.Writer(f, linktype=1)
        writer.writepkt(b"\x00" * 10, ts=1.0)
        writer.writepkt(b"\x00" * 10, ts=2.0)
    full_size = os.path.getsize(src)
    # Chop deep enough to sever the SECOND record's own 16-byte header (not
    # just a couple of trailing payload bytes), simulating a recorder killed
    # mid-write (the real bug this function was hardened against) — this is
    # what actually makes dpkt raise NeedData while iterating.
    with open(src, "r+b") as f:
        f.truncate(full_size - 20)

    out = tmp_path / "trimmed.pcap"
    # Should not raise despite the truncated trailing record.
    n = p2p.extract_scenario_pcap(str(src), str(out), start_ns=0, end_ns=int(10e9))
    assert n == 1  # only the first, complete record survives
