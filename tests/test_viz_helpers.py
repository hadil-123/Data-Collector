import base64
import csv
import os

import numpy as np
import pytest

import viz_helpers as vh
import pcap_to_pcd as p2p


# ---------------------------------------------------------------------------
# iPhone video filename timestamp parsing
# ---------------------------------------------------------------------------

def test_parse_ios_video_epoch_matches_filename_convention():
    # "20261031_184748000_iOS.mp4" is UTC per the confirmed -4h offset check
    # against the phone's own displayed (EDT) timestamp.
    import datetime
    ts = vh.parse_ios_video_epoch("20261031_184748000_iOS.mp4")
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    assert dt.year == 2026 and dt.month == 10 and dt.day == 31
    assert dt.hour == 18 and dt.minute == 47 and dt.second == 48


def test_parse_ios_video_epoch_handles_duplicate_take_suffix():
    # iOS appends " 2" etc. to filenames for a second simultaneous recording
    # (two phones starting at the same second) — the regex must still match
    # the leading timestamp despite the " 2.mp4" suffix.
    assert vh.parse_ios_video_epoch("20261031_190250000_iOS 2.mp4") is not None
    assert vh.parse_ios_video_epoch("20261031_190250000_iOS.mp4") == \
        vh.parse_ios_video_epoch("20261031_190250000_iOS 2.mp4")


def test_parse_ios_video_epoch_rejects_unrelated_filenames():
    assert vh.parse_ios_video_epoch("random_file.mp4") is None
    assert vh.parse_ios_video_epoch("A1_prise1_cam1.mp4") is None


# ---------------------------------------------------------------------------
# find_covering_clips
# ---------------------------------------------------------------------------

def test_find_covering_clips_matches_file_spanning_the_window():
    videos = [
        {"path": "a.mp4", "name": "a.mp4", "start": 100.0, "end": 200.0},
        {"path": "b.mp4", "name": "b.mp4", "start": 500.0, "end": 600.0},
    ]
    clips = vh.find_covering_clips(videos, start_epoch_s=120.0, end_epoch_s=150.0, margin=2.0)
    assert len(clips) == 1
    assert clips[0]["file"]["name"] == "a.mp4"
    assert clips[0]["offset"] == pytest.approx(18.0)  # 120 - 100 - 2
    assert clips[0]["duration"] == pytest.approx(34.0)  # (150-120) + 2 + 2


def test_find_covering_clips_excludes_files_that_dont_fully_cover():
    videos = [{"path": "a.mp4", "name": "a.mp4", "start": 100.0, "end": 140.0}]
    # scenario window extends past the end of the only available clip
    clips = vh.find_covering_clips(videos, start_epoch_s=120.0, end_epoch_s=150.0)
    assert clips == []


def test_find_covering_clips_offset_never_negative_near_file_start():
    videos = [{"path": "a.mp4", "name": "a.mp4", "start": 100.0, "end": 200.0}]
    # scenario starts right at (or within margin of) the file's own start
    clips = vh.find_covering_clips(videos, start_epoch_s=100.5, end_epoch_s=110.0, margin=2.0)
    assert clips[0]["offset"] == 0.0


def test_find_covering_clips_matches_multiple_simultaneous_cameras():
    videos = [
        {"path": "cam1.mp4", "name": "cam1.mp4", "start": 0.0, "end": 1000.0},
        {"path": "cam2.mp4", "name": "cam2.mp4", "start": 0.0, "end": 1000.0},
    ]
    clips = vh.find_covering_clips(videos, start_epoch_s=10.0, end_epoch_s=20.0)
    assert len(clips) == 2


# ---------------------------------------------------------------------------
# Path builders
# ---------------------------------------------------------------------------

def test_video_path_includes_take_number_one_based():
    p = vh.video_path("/base/session", "lidar_A", "A1", take_idx=0)
    assert p.endswith(os.path.join("lidar_A", "pcd", "A1_prise1.mp4"))
    p2 = vh.video_path("/base/session", "lidar_A", "A1", take_idx=2)
    assert p2.endswith("A1_prise3.mp4")


def test_pcd_dir_builds_expected_path():
    p = vh.pcd_dir("/base/session", "lidar_B", "M3")
    assert p == os.path.join("/base/session", "derived", "lidar_B", "pcd", "M3")


# ---------------------------------------------------------------------------
# Filesystem scanning helpers
# ---------------------------------------------------------------------------

def test_find_scenario_ids_lists_only_subdirectories(tmp_path):
    pcd_a = tmp_path / "session" / "derived" / "lidar_A" / "pcd"
    (pcd_a / "A1").mkdir(parents=True)
    (pcd_a / "D1").mkdir(parents=True)
    (pcd_a / "manifest.csv").write_text("not a dir")
    ids = vh.find_scenario_ids(str(tmp_path / "session"))
    assert ids == ["A1", "D1"]


def test_find_scenario_ids_missing_session_returns_empty():
    assert vh.find_scenario_ids("/nonexistent/path") == []


def test_find_sessions_requires_lidar_a_pcd_dir(tmp_path):
    valid = tmp_path / "Imed" / "S001_P01_20260101_000000"
    (valid / "derived" / "lidar_A" / "pcd").mkdir(parents=True)
    incomplete = tmp_path / "Other" / "S001_P01_20260101_000001"
    incomplete.mkdir(parents=True)  # no derived/lidar_A/pcd — not a real session yet

    sessions = vh.find_sessions(str(tmp_path))
    assert str(valid) in sessions
    assert not any(str(incomplete) == s for s in sessions)


def test_find_sessions_finds_sessions_nested_more_than_one_level_deep(tmp_path):
    # "Data Root Dir" is free text (e.g. "data/Hadil" instead of just "data"),
    # so a session can land more than one directory level under base_dir.
    nested = tmp_path / "data" / "Hadil" / "S001_P01_20261104_174712"
    (nested / "derived" / "lidar_A" / "pcd").mkdir(parents=True)

    sessions = vh.find_sessions(str(tmp_path))
    assert str(nested) in sessions


def test_find_sessions_does_not_descend_into_matched_session_dirs(tmp_path):
    # A scenario id inside a matched session's own pcd/ output could in
    # theory look like a session name too (unlikely, but find_sessions
    # should never need to look there) -- assert the walk is pruned.
    valid = tmp_path / "S001_P01_20260101_000000"
    (valid / "derived" / "lidar_A" / "pcd").mkdir(parents=True)
    decoy = valid / "derived" / "lidar_A" / "pcd" / "S002_P01_decoy"
    (decoy / "derived" / "lidar_A" / "pcd").mkdir(parents=True)

    sessions = vh.find_sessions(str(tmp_path))
    assert sessions == [str(valid)]


# ---------------------------------------------------------------------------
# load_sync_pairs
# ---------------------------------------------------------------------------

def test_load_sync_pairs_reads_rows(tmp_path):
    session = tmp_path / "session"
    (session / "derived").mkdir(parents=True)
    sync_csv = session / "derived" / "sync_A1.csv"
    with open(sync_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a_frame_index", "a_filename", "a_epoch_ns", "a_num_points",
                    "b_frame_index", "b_filename", "b_epoch_ns", "b_num_points",
                    "delta_ms", "flagged"])
        w.writerow([0, "000000_100.pcd", 100, 500, 0, "000000_102.pcd", 102, 480, 2.0, ""])
    rows = vh.load_sync_pairs(str(session), "A1")
    assert len(rows) == 1
    assert rows[0]["a_filename"] == "000000_100.pcd"


def test_load_sync_pairs_missing_file_returns_empty_list(tmp_path):
    assert vh.load_sync_pairs(str(tmp_path), "NOPE") == []


# ---------------------------------------------------------------------------
# frame_arrays: Z-flip for ceiling-mounted sensors + downsampling
# ---------------------------------------------------------------------------

def test_frame_arrays_inverts_z_axis(tmp_path):
    path = tmp_path / "f.pcd"
    pts = [[1.0, 2.0, 3.0, 50.0, 0.0, 0.0, 0.0, 0.0]]
    p2p.write_pcd_binary(str(path), np.array(pts, dtype="<f4"))

    x, y, z, c = vh.frame_arrays(str(path), max_points=10000)
    assert x[0] == pytest.approx(1.0)
    assert y[0] == pytest.approx(2.0)
    assert z[0] == pytest.approx(-3.0)  # sensors are ceiling-mounted upside down
    assert c[0] == pytest.approx(50.0)


def test_frame_arrays_downsamples_when_over_cap(tmp_path):
    path = tmp_path / "f.pcd"
    rng = np.random.default_rng(1)
    pts = rng.normal(size=(500, 8)).astype("<f4")
    p2p.write_pcd_binary(str(path), pts)

    x, y, z, c = vh.frame_arrays(str(path), max_points=100)
    assert x.shape[0] == 100


def test_frame_arrays_empty_frame_returns_empty_arrays(tmp_path):
    path = tmp_path / "empty.pcd"
    p2p.write_pcd_binary(str(path), np.zeros((0, 8), dtype="<f4"))
    x, y, z, c = vh.frame_arrays(str(path), max_points=100)
    assert x.shape[0] == 0 and y.shape[0] == 0 and z.shape[0] == 0 and c.shape[0] == 0


# ---------------------------------------------------------------------------
# b64f32 encoding round trip
# ---------------------------------------------------------------------------

def test_b64f32_round_trips_through_base64():
    chunks = [np.array([1.0, 2.0, 3.0], dtype="<f4"), np.array([4.5], dtype="<f4")]
    encoded = vh.b64f32(chunks)
    decoded = np.frombuffer(base64.b64decode(encoded), dtype="<f4")
    np.testing.assert_allclose(decoded, [1.0, 2.0, 3.0, 4.5])


def test_b64f32_empty_input_produces_valid_empty_buffer():
    assert vh.b64f32([]) == base64.b64encode(b"").decode("ascii")


# ---------------------------------------------------------------------------
# dual_pcd_viewer_html: just check it produces well-formed, data-carrying HTML
# ---------------------------------------------------------------------------

def test_dual_pcd_viewer_html_embeds_frame_count_and_labels(tmp_path):
    dir_a = tmp_path / "A"
    dir_b = tmp_path / "B"
    dir_a.mkdir()
    dir_b.mkdir()
    pts = np.array([[0.0, 0.0, 0.0, 10.0, 0, 0, 0, 0]], dtype="<f4")
    p2p.write_pcd_binary(str(dir_a / "f0.pcd"), pts)
    p2p.write_pcd_binary(str(dir_b / "f0.pcd"), pts)

    rows = [{"a_filename": "f0.pcd", "b_filename": "f0.pcd",
              "a_frame_index": "0", "b_frame_index": "0", "delta_ms": "1.0"}]
    html = vh.dual_pcd_viewer_html(rows, str(dir_a), str(dir_b), plotlyjs="/* fake plotly.js */")

    assert "plotA" in html and "plotB" in html
    assert "Frame A #0" in html
    assert "/* fake plotly.js */" in html
