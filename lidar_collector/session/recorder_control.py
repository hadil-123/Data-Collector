"""Launching/checking the recorder and RosBag subprocesses used while a
session is live, and the ROS pre-flight checks run before starting them."""
import os
import shlex
import signal
import shutil
import subprocess


def detect_rosbag_mode():
    if shutil.which("ros2"):
        return "ros2"
    if shutil.which("rosbag"):
        return "ros1"
    return None


def build_rosbag_command(mode, rosbag_dir, sensor_tag, topic):
    if mode == "ros2":
        output_base = os.path.join(rosbag_dir, f"lidar_{sensor_tag}_ros2")
        return ["ros2", "bag", "record", "-o", output_base, topic], output_base
    output_file = os.path.join(rosbag_dir, f"lidar_{sensor_tag}_ros1.bag")
    return ["rosbag", "record", "-O", output_file, topic], output_file


def run_check_command(cmd):
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def preflight_ros(mode, topics):
    if mode == "ros2":
        ok, out, err = run_check_command(["ros2", "topic", "list"])
        if not ok:
            return False, f"ROS2 indisponible: {err or 'commande ros2 topic list en erreur'}"
        available = set([line.strip() for line in out.splitlines() if line.strip()])
        missing = [t for t in topics if t not in available]
        if missing:
            return False, f"Topics ROS2 absents: {', '.join(missing)}"
        return True, "Pre-vol ROS2 OK"

    ok, out, err = run_check_command(["rostopic", "list"])
    if not ok:
        return False, f"ROS1/roscore indisponible: {err or 'commande rostopic list en erreur'}"
    available = set([line.strip() for line in out.splitlines() if line.strip()])
    missing = [t for t in topics if t not in available]
    if missing:
        return False, f"Topics ROS1 absents: {', '.join(missing)}"
    return True, "Pre-vol ROS1 OK"


def launch_bg_command(command_text, log_path):
    cmd = shlex.split(command_text)
    if not cmd:
        raise RuntimeError("Commande vide")
    with open(log_path, "ab") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            preexec_fn=os.setsid
        )
    return proc


def stop_process_group(proc):
    if not proc:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        pass
