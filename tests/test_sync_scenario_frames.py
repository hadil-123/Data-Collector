import csv

import sync_scenario_frames as ssf


def test_pair_nearest_matches_closest_timestamp():
    rows_a = [{"epoch_ns": 100}, {"epoch_ns": 200}, {"epoch_ns": 300}]
    rows_b = [{"epoch_ns": 95}, {"epoch_ns": 205}, {"epoch_ns": 310}]
    pairs = ssf.pair_nearest(rows_a, rows_b)
    assert [b["epoch_ns"] for _, b in pairs] == [95, 205, 310]


def test_pair_nearest_handles_missing_b_frame_gap():
    # B is missing a frame around 200 (dropped packet) — A's frame at 200
    # should still pair with whichever B frame is numerically closest.
    rows_a = [{"epoch_ns": 100}, {"epoch_ns": 200}, {"epoch_ns": 300}]
    rows_b = [{"epoch_ns": 100}, {"epoch_ns": 290}]
    pairs = ssf.pair_nearest(rows_a, rows_b)
    assert [b["epoch_ns"] for _, b in pairs] == [100, 290, 290]


def test_pair_nearest_empty_b_returns_none():
    rows_a = [{"epoch_ns": 100}]
    pairs = ssf.pair_nearest(rows_a, [])
    assert pairs == [(rows_a[0], None)]


def _write_manifest(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "epoch_ns", "filename", "num_points", "scenario_id"])
        for i, epoch_ns in enumerate(rows):
            w.writerow([i, epoch_ns, f"{i:06d}_{epoch_ns}.pcd", 1000, "A1"])


def test_sync_manifests_writes_combined_csv_and_flags_large_gaps(tmp_path):
    manifest_a = tmp_path / "a.csv"
    manifest_b = tmp_path / "b.csv"
    out = tmp_path / "sync.csv"

    # 100ms cadence; one far-apart pair (200ms gap) should get flagged at
    # the default 70ms threshold, the rest should not.
    _write_manifest(manifest_a, [0, 100_000_000, 200_000_000])
    _write_manifest(manifest_b, [5_000_000, 110_000_000, 400_000_000])

    n_pairs, n_flagged = ssf.sync_manifests(str(manifest_a), str(manifest_b), str(out))
    assert n_pairs == 3
    assert n_flagged == 1

    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[2]["flagged"] == "yes"
    assert rows[0]["flagged"] == ""


def test_sync_manifests_raises_on_empty_manifest(tmp_path):
    manifest_a = tmp_path / "a.csv"
    manifest_b = tmp_path / "b.csv"
    _write_manifest(manifest_a, [])
    _write_manifest(manifest_b, [0])
    try:
        ssf.sync_manifests(str(manifest_a), str(manifest_b), str(tmp_path / "out.csv"))
        assert False, "expected ValueError for empty manifest"
    except ValueError:
        pass
