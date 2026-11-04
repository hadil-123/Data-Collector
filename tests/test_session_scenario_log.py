import os

import yaml

from lidar_collector.session import scenario_log as sl


def test_update_session_meta_creates_file(tmp_path):
    base = tmp_path
    (base / "meta").mkdir()
    sl.update_session_meta(str(base), {"a": 1})
    with open(base / "meta" / "session_meta.yaml") as f:
        data = yaml.safe_load(f)
    assert data == {"a": 1}


def test_update_session_meta_merges(tmp_path):
    base = tmp_path
    (base / "meta").mkdir()
    sl.update_session_meta(str(base), {"a": 1, "b": 2})
    sl.update_session_meta(str(base), {"b": 3, "c": 4})
    with open(base / "meta" / "session_meta.yaml") as f:
        data = yaml.safe_load(f)
    assert data == {"a": 1, "b": 3, "c": 4}


def test_update_session_meta_swallows_errors(tmp_path):
    # base_path's meta/ dir doesn't exist -> write fails -> must not raise.
    sl.update_session_meta(str(tmp_path / "nope"), {"a": 1})


def _write_log(path, rows):
    header = "event,hh:mm:ss,elapsed_sec,epoch_ns,scenario_id,scenario_label,zone,num_people,occlusion,notes,status\n"
    with open(path, "w") as f:
        f.write(header)
        for row in rows:
            f.write(row + "\n")


def test_find_open_scenario_none_when_missing_file(tmp_path):
    assert sl.find_open_scenario(str(tmp_path / "nope.csv")) is None
    assert sl.find_open_scenario(None) is None


def test_find_open_scenario_detects_unclosed(tmp_path):
    p = tmp_path / "log.csv"
    _write_log(p, [
        "scenario_start,10:00:00,0,1000,A1,Label,Z1,1,none,,ok",
    ])
    result = sl.find_open_scenario(str(p))
    assert result == ("A1", "1000")


def test_find_open_scenario_none_when_closed(tmp_path):
    p = tmp_path / "log.csv"
    _write_log(p, [
        "scenario_start,10:00:00,0,1000,A1,Label,Z1,1,none,,ok",
        "scenario_end,10:00:30,30,1030,A1,Label,Z1,1,none,,ok",
    ])
    assert sl.find_open_scenario(str(p)) is None


def test_find_open_scenario_tracks_latest_start(tmp_path):
    p = tmp_path / "log.csv"
    _write_log(p, [
        "scenario_start,10:00:00,0,1000,A1,Label,Z1,1,none,,ok",
        "scenario_end,10:00:30,30,1030,A1,Label,Z1,1,none,,ok",
        "scenario_start,10:01:00,60,1060,A2,Label2,Z2,1,none,,ok",
    ])
    assert sl.find_open_scenario(str(p)) == ("A2", "1060")


def test_scenario_completion_counts(tmp_path):
    p = tmp_path / "log.csv"
    _write_log(p, [
        "scenario_start,10:00:00,0,1000,A1,Label,Z1,1,none,,ok",
        "scenario_end,10:00:30,30,1030,A1,Label,Z1,1,none,,ok",
        "scenario_start,10:01:00,60,1060,A1,Label,Z1,1,none,,ok",
        "scenario_end,10:01:30,90,1090,A1,Label,Z1,1,none,,ok",
        "scenario_start,10:02:00,120,1120,A2,Label2,Z2,1,none,,ok",
        "scenario_end,10:02:30,150,1150,A2,Label2,Z2,1,none,,ok",
    ])
    assert sl.scenario_completion_counts(str(p)) == {"A1": 2, "A2": 1}


def test_scenario_completion_counts_empty_when_missing(tmp_path):
    assert sl.scenario_completion_counts(str(tmp_path / "nope.csv")) == {}
    assert sl.scenario_completion_counts(None) == {}


def test_initialize_session_logs_single_sensor(tmp_path):
    scenario_log = tmp_path / "session_log.csv"
    lidar_a_log = tmp_path / "lidar_A_log.csv"
    sl.initialize_session_logs(str(scenario_log), str(lidar_a_log), None, 1_700_000_000_000_000_000, False)

    session_text = scenario_log.read_text()
    assert "session_start" in session_text
    assert ",ok,disabled\n" in session_text
    assert lidar_a_log.read_text().startswith("event,hh:mm:ss,elapsed_sec,epoch_ns,scenario_id")


def test_initialize_session_logs_dual_sensor(tmp_path):
    scenario_log = tmp_path / "session_log.csv"
    lidar_a_log = tmp_path / "lidar_A_log.csv"
    lidar_b_log = tmp_path / "lidar_B_log.csv"
    sl.initialize_session_logs(
        str(scenario_log), str(lidar_a_log), str(lidar_b_log), 1_700_000_000_000_000_000, True,
    )
    assert ",ok,ok\n" in scenario_log.read_text()
    assert lidar_b_log.exists()
