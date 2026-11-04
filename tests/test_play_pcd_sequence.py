import math
import os

import numpy as np
import pytest

import play_pcd_sequence as pps
import pcap_to_pcd as p2p


def test_frame_epoch_from_path_parses_embedded_timestamp():
    assert pps.frame_epoch_from_path("/a/b/000005_1793472944274656722.pcd") == 1793472944274656722
    assert pps.frame_epoch_from_path("000000_42.pcd") == 42


def test_filter_files_by_epoch_keeps_only_in_range_frames():
    files = [f"{i:06d}_{epoch}.pcd" for i, epoch in enumerate([100, 200, 300, 400])]
    kept = pps.filter_files_by_epoch(files, start_ns=200, end_ns=300)
    assert kept == files[1:3]


def test_filter_files_by_epoch_no_bounds_returns_all():
    files = ["000000_1.pcd", "000001_2.pcd"]
    assert pps.filter_files_by_epoch(files) == files


def test_filter_files_by_epoch_open_ended_bounds():
    files = [f"{i:06d}_{epoch}.pcd" for i, epoch in enumerate([100, 200, 300])]
    assert pps.filter_files_by_epoch(files, start_ns=200) == files[1:]
    assert pps.filter_files_by_epoch(files, end_ns=200) == files[:2]


def test_eye_level_camera_position_elevation_angle():
    # A symmetric room bounding box centered on the origin.
    bounds = (-5, 5, -5, 5, -1, 1)
    cam, target, up = pps.eye_level_camera_position(bounds, elevation_deg=22)
    assert up == (0, 0, 1)
    assert target == (0.0, 0.0, 0.0)
    # The camera should sit above the target (positive Z) and back from it
    # (nonzero X/Y), roughly honoring the requested elevation angle.
    cx, cy, cz = cam
    assert cz > 0
    horiz_dist = math.hypot(cx, cy)
    actual_elev_deg = math.degrees(math.atan2(cz, horiz_dist))
    assert actual_elev_deg == pytest.approx(22, abs=1.0)
    # Looks from the +X/+Y corner (see "vise depuis le coin oppose" comment).
    assert cx > 0 and cy > 0


def test_eye_level_camera_position_handles_degenerate_bounds():
    # A single point (zero-size bounding box) shouldn't produce a
    # zero-distance / NaN camera position.
    bounds = (0, 0, 0, 0, 0, 0)
    cam, target, up = pps.eye_level_camera_position(bounds)
    assert all(math.isfinite(c) for c in cam)
    assert math.hypot(*cam) > 0


def _write_fake_pcd(path, xyz_intensity):
    pts = np.array(xyz_intensity, dtype="<f4")
    p2p.write_pcd_binary(str(path), pts)


def test_estimate_sequence_bounds_percentile_bounding_box(tmp_path):
    files = []
    rng = np.random.default_rng(0)
    for i in range(10):
        pts = rng.normal(loc=0, scale=1, size=(50, 8)).astype("<f4")
        path = tmp_path / f"{i:06d}_{i}.pcd"
        _write_fake_pcd(path, pts)
        files.append(str(path))

    bounds = pps.estimate_sequence_bounds(files, sample=10, pad_ratio=0.0)
    assert bounds is not None
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    # With ~500 normal(0,1) samples pooled, bounds should be a few sigma wide
    # around zero, not degenerate.
    assert xmin < 0 < xmax
    assert ymin < 0 < ymax
    assert zmin < 0 < zmax


def test_estimate_sequence_bounds_robust_to_single_outlier_frame(tmp_path):
    # One frame has a wild outlier point; estimate_sequence_bounds uses
    # 1st-99th percentiles pooled across many frames specifically so a
    # single stray point can't blow up the camera framing.
    files = []
    for i in range(20):
        if i == 0:
            pts = [[1000.0, 1000.0, 1000.0, 1, 0, 0, 0, 0]]
        else:
            pts = [[float(i % 3), float(i % 2), 0.1, 1, 0, 0, 0, 0] for _ in range(5)]
        path = tmp_path / f"{i:06d}_{i}.pcd"
        _write_fake_pcd(path, pts)
        files.append(str(path))

    bounds = pps.estimate_sequence_bounds(files, sample=20, pad_ratio=0.1)
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    assert xmax < 100  # the 1000.0 outlier must not dominate the bounds


def test_estimate_sequence_bounds_empty_file_list_returns_none():
    assert pps.estimate_sequence_bounds([]) is None


def test_read_pcd_binary_round_trip_matches_written_values(tmp_path):
    path = tmp_path / "f.pcd"
    pts = [[1.0, -2.0, 3.5, 77.0, 0.0, 0.0, 1.0, 0.0]]
    _write_fake_pcd(path, pts)
    arr = pps.read_pcd_binary(str(path))
    assert arr.shape[0] == 1
    assert arr["x"][0] == pytest.approx(1.0)
    assert arr["y"][0] == pytest.approx(-2.0)
    assert arr["z"][0] == pytest.approx(3.5)
    assert arr["intensity"][0] == pytest.approx(77.0)
