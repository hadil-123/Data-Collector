import os

from lidar_collector.session import recorder_control as rc


def test_detect_rosbag_mode_none(monkeypatch):
    monkeypatch.setattr(rc.shutil, "which", lambda name: None)
    assert rc.detect_rosbag_mode() is None


def test_detect_rosbag_mode_ros2(monkeypatch):
    monkeypatch.setattr(rc.shutil, "which", lambda name: "/usr/bin/ros2" if name == "ros2" else None)
    assert rc.detect_rosbag_mode() == "ros2"


def test_detect_rosbag_mode_ros1(monkeypatch):
    monkeypatch.setattr(rc.shutil, "which", lambda name: "/usr/bin/rosbag" if name == "rosbag" else None)
    assert rc.detect_rosbag_mode() == "ros1"


def test_build_rosbag_command_ros2(tmp_path):
    cmd, output = rc.build_rosbag_command("ros2", str(tmp_path), "A", "/lidar_a/points")
    assert cmd == ["ros2", "bag", "record", "-o", str(tmp_path / "lidar_A_ros2"), "/lidar_a/points"]
    assert output == str(tmp_path / "lidar_A_ros2")


def test_build_rosbag_command_ros1(tmp_path):
    cmd, output = rc.build_rosbag_command("ros1", str(tmp_path), "B", "/lidar_b/points")
    assert cmd == ["rosbag", "record", "-O", str(tmp_path / "lidar_B_ros1.bag"), "/lidar_b/points"]
    assert output == str(tmp_path / "lidar_B_ros1.bag")


def test_run_check_command_success():
    ok, out, err = rc.run_check_command(["echo", "hello"])
    assert ok
    assert out == "hello"


def test_run_check_command_failure():
    ok, out, err = rc.run_check_command(["false"])
    assert not ok


def test_run_check_command_missing_binary():
    ok, out, err = rc.run_check_command(["/nonexistent/binary/xyz"])
    assert not ok
    assert err


def test_preflight_ros_ros2_missing_topic(monkeypatch):
    monkeypatch.setattr(rc, "run_check_command", lambda cmd: (True, "/lidar_a/points\n", ""))
    ok, msg = rc.preflight_ros("ros2", ["/lidar_a/points", "/lidar_b/points"])
    assert not ok
    assert "/lidar_b/points" in msg


def test_preflight_ros_ros2_all_present(monkeypatch):
    monkeypatch.setattr(rc, "run_check_command", lambda cmd: (True, "/lidar_a/points\n/lidar_b/points\n", ""))
    ok, msg = rc.preflight_ros("ros2", ["/lidar_a/points", "/lidar_b/points"])
    assert ok


def test_preflight_ros_ros2_unavailable(monkeypatch):
    monkeypatch.setattr(rc, "run_check_command", lambda cmd: (False, "", "command not found"))
    ok, msg = rc.preflight_ros("ros2", ["/lidar_a/points"])
    assert not ok
    assert "ROS2 indisponible" in msg


def test_preflight_ros_ros1_all_present(monkeypatch):
    monkeypatch.setattr(rc, "run_check_command", lambda cmd: (True, "/lidar_a/points\n", ""))
    ok, msg = rc.preflight_ros("ros1", ["/lidar_a/points"])
    assert ok


def test_launch_bg_command_empty_raises(tmp_path):
    import pytest
    with pytest.raises(RuntimeError):
        rc.launch_bg_command("   ", str(tmp_path / "log.txt"))


def test_launch_bg_command_and_stop(tmp_path):
    log_path = tmp_path / "log.txt"
    proc = rc.launch_bg_command("sleep 5", str(log_path))
    assert proc.poll() is None
    rc.stop_process_group(proc)
    assert proc.poll() is not None


def test_stop_process_group_none_is_noop():
    rc.stop_process_group(None)
