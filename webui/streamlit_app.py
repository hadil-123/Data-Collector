import streamlit as st
import subprocess
import os
import sys
import yaml
import shutil
import signal
import shlex
import csv
from datetime import datetime
import time
import re

# DEMO MODE - pour tester sans capteur réel
DEMO_MODE = False

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)  # Up one level from webui/

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'scripts'))
import pcap_to_pcd  # noqa: E402 - needs sys.path set up first
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'configs', 'ui_config.yaml')
SENSORS_PATH = os.path.join(PROJECT_ROOT, 'configs', 'sensors.yaml')
SCENARIOS_PATH = os.path.join(PROJECT_ROOT, 'configs', 'scenarios.yaml')
DEFAULT_SENSORS_CFG = {
    'sensor_a': {'ip': '192.168.1.202'},
    'port': 2368,
    'interface': 'eth0',
}

# Load configs with error handling
try:
    with open(CONFIG_PATH) as f:
        UI_CFG = yaml.safe_load(f)
except:
    UI_CFG = {'session_data_root': 'data/'}

try:
    with open(SENSORS_PATH) as f:
        loaded_cfg = yaml.safe_load(f) or {}
except:
    loaded_cfg = {}

if not isinstance(loaded_cfg, dict):
    loaded_cfg = {}

sensor_a_cfg = loaded_cfg.get('sensor_a') if isinstance(loaded_cfg.get('sensor_a'), dict) else {}
sensor_b_cfg = loaded_cfg.get('sensor_b') if isinstance(loaded_cfg.get('sensor_b'), dict) else {}
sensor_b_available = isinstance(sensor_b_cfg, dict) and bool(sensor_b_cfg.get('ip'))

SENSORS_CFG = {
    'sensor_a': {'ip': sensor_a_cfg.get('ip', DEFAULT_SENSORS_CFG['sensor_a']['ip'])},
    'sensor_b': {'available': sensor_b_available, 'ip': sensor_b_cfg.get('ip', '')},
    'port': int(loaded_cfg.get('port', DEFAULT_SENSORS_CFG['port'])),
    'interface': loaded_cfg.get('interface', DEFAULT_SENSORS_CFG['interface']),
}
SENSOR_B_AVAILABLE = SENSORS_CFG['sensor_b']['available']


def resolve_recorder_binary():
    candidates = [
        os.path.join(PROJECT_ROOT, 'recorder', 'recorder'),
        os.path.join(PROJECT_ROOT, 'recorder', 'build', 'recorder'),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def now_epoch_ns():
    return time.time_ns()


def fmt_hms_from_ns(epoch_ns):
    return datetime.fromtimestamp(epoch_ns / 1e9).strftime('%H:%M:%S')


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


def update_session_meta(base_path, updates):
    meta_path = os.path.join(base_path, 'meta', 'session_meta.yaml')
    try:
        current = {}
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                current = yaml.safe_load(f) or {}
        current.update(updates)
        with open(meta_path, 'w') as f:
            yaml.dump(current, f)
    except Exception:
        pass


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
    try:
        probe = path if os.path.isdir(path) else os.path.dirname(path) or "."
        usage = shutil.disk_usage(probe)
        return usage.free, usage.total
    except OSError:
        return None, None


def find_open_scenario(log_path):
    """Return (scenario_id, start_epoch_ns) for a scenario_start with no
    matching scenario_end yet (i.e. currently in progress), or None."""
    if not log_path or not os.path.exists(log_path):
        return None
    open_scenario = None
    try:
        with open(log_path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("event") == "scenario_start":
                    open_scenario = (row.get("scenario_id"), row.get("epoch_ns"))
                elif row.get("event") == "scenario_end" and open_scenario and row.get("scenario_id") == open_scenario[0]:
                    open_scenario = None
    except OSError:
        return None
    return open_scenario


def scenario_completion_counts(log_path):
    """{scenario_id: number of completed takes} this session, from scenario_end rows."""
    counts = {}
    if not log_path or not os.path.exists(log_path):
        return counts
    try:
        with open(log_path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("event") == "scenario_end":
                    sid = row.get("scenario_id")
                    counts[sid] = counts.get(sid, 0) + 1
    except OSError:
        pass
    return counts


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


def initialize_session_logs(scenario_log_path, lidar_a_log_path, lidar_b_log_path, start_epoch_ns, use_sensor_b):
    with open(scenario_log_path, 'w') as f:
        f.write("event,hh:mm:ss,elapsed_sec,epoch_ns,lidar_a_status,lidar_b_status\n")
        lidar_b_status = "ok" if use_sensor_b else "disabled"
        f.write(f"session_start,{fmt_hms_from_ns(start_epoch_ns)},0,{start_epoch_ns},ok,{lidar_b_status}\n")

    with open(lidar_a_log_path, 'w') as f:
        f.write("event,hh:mm:ss,elapsed_sec,epoch_ns,scenario_id,scenario_label,zone,num_people,occlusion,notes,status\n")

    if lidar_b_log_path:
        with open(lidar_b_log_path, 'w') as f:
            f.write("event,hh:mm:ss,elapsed_sec,epoch_ns,scenario_id,scenario_label,zone,num_people,occlusion,notes,status\n")


def reset_runtime_state(clear_session_context=False):
    st.session_state.rosbag_proc_a = None
    st.session_state.rosbag_proc_b = None
    st.session_state.ros_driver_b_proc = None
    st.session_state.ros_driver_a_proc = None
    st.session_state.roscore_proc = None
    st.session_state.recorder_proc = None
    st.session_state.session_rosbag_mode = None
    st.session_state.session_rosbag_output_a = None
    st.session_state.session_rosbag_output_b = None
    st.session_state.rosbag_log_path_a = None
    st.session_state.rosbag_log_path_b = None
    st.session_state.recorder_log_path = None
    st.session_state.recorder_start_epoch_ns = None
    st.session_state.rosbag_start_epoch_ns_a = None
    st.session_state.rosbag_start_epoch_ns_b = None
    st.session_state.ros_prereq_log_path = None
    if clear_session_context:
        st.session_state.session_base = None
        st.session_state.session_sensor_b_enabled = False
        st.session_state.live_monitor_history = []


try:
    with open(SCENARIOS_PATH, encoding='utf-8') as f:
        SCENARIOS_CFG = yaml.safe_load(f)
except:
    SCENARIOS_CFG = {'scenarios': [
        {'id': 'SC01', 'label': 'Marche simple'},
        {'id': 'SC02', 'label': 'Obstacle statique'},
        {'id': 'SC03', 'label': 'Croisement'}
    ]}

# Streamlit Config
st.set_page_config(page_title="Lidar Session Manager", layout="wide", initial_sidebar_state="expanded")

# Session state
if 'recorder_proc' not in st.session_state:
    st.session_state.recorder_proc = None
if 'session_base' not in st.session_state:
    st.session_state.session_base = None
if 'scenario_log_path' not in st.session_state:
    st.session_state.scenario_log_path = None
if 'lidar_a_log_path' not in st.session_state:
    st.session_state.lidar_a_log_path = None
if 'lidar_b_log_path' not in st.session_state:
    st.session_state.lidar_b_log_path = None
if 'data_root' not in st.session_state:
    st.session_state.data_root = UI_CFG['session_data_root']
if 'sensor_a_ip' not in st.session_state:
    st.session_state.sensor_a_ip = SENSORS_CFG['sensor_a']['ip']
if 'sensor_b_ip' not in st.session_state:
    st.session_state.sensor_b_ip = SENSORS_CFG['sensor_b']['ip']
if 'port' not in st.session_state:
    st.session_state.port = SENSORS_CFG['port']
if 'session_start_time' not in st.session_state:
    st.session_state.session_start_time = None
if 'session_start_epoch_ns' not in st.session_state:
    st.session_state.session_start_epoch_ns = None
if 'use_sensor_b' not in st.session_state:
    st.session_state.use_sensor_b = SENSOR_B_AVAILABLE
if 'session_sensor_b_enabled' not in st.session_state:
    st.session_state.session_sensor_b_enabled = False
if 'rosbag_proc_a' not in st.session_state:
    st.session_state.rosbag_proc_a = None
if 'rosbag_proc_b' not in st.session_state:
    st.session_state.rosbag_proc_b = None
if 'enable_rosbag' not in st.session_state:
    st.session_state.enable_rosbag = False
if 'enable_bag' not in st.session_state:
    st.session_state.enable_bag = False
if 'rosbag_topic_a' not in st.session_state:
    st.session_state.rosbag_topic_a = "/lidar_a/velodyne_points"
if 'rosbag_topic_b' not in st.session_state:
    st.session_state.rosbag_topic_b = "/lidar_b/velodyne_points"
if st.session_state.rosbag_topic_a == "/lidar_a/points":
    st.session_state.rosbag_topic_a = "/lidar_a/velodyne_points"
if st.session_state.rosbag_topic_b == "/lidar_b/points":
    st.session_state.rosbag_topic_b = "/lidar_b/velodyne_points"
if 'session_rosbag_mode' not in st.session_state:
    st.session_state.session_rosbag_mode = None
if 'session_rosbag_output_a' not in st.session_state:
    st.session_state.session_rosbag_output_a = None
if 'session_rosbag_output_b' not in st.session_state:
    st.session_state.session_rosbag_output_b = None
if 'rosbag_log_path_a' not in st.session_state:
    st.session_state.rosbag_log_path_a = None
if 'rosbag_log_path_b' not in st.session_state:
    st.session_state.rosbag_log_path_b = None
if 'ros_prereq_log_path' not in st.session_state:
    st.session_state.ros_prereq_log_path = None
if 'enable_ros_autolaunch' not in st.session_state:
    st.session_state.enable_ros_autolaunch = False
if 'roscore_cmd' not in st.session_state:
    st.session_state.roscore_cmd = "roscore"
if 'ros_driver_a_cmd' not in st.session_state:
    st.session_state.ros_driver_a_cmd = ""
if 'ros_driver_b_cmd' not in st.session_state:
    st.session_state.ros_driver_b_cmd = ""
if 'roscore_proc' not in st.session_state:
    st.session_state.roscore_proc = None
if 'ros_driver_a_proc' not in st.session_state:
    st.session_state.ros_driver_a_proc = None
if 'ros_driver_b_proc' not in st.session_state:
    st.session_state.ros_driver_b_proc = None
if 'recorder_log_path' not in st.session_state:
    st.session_state.recorder_log_path = None
if 'recorder_start_epoch_ns' not in st.session_state:
    st.session_state.recorder_start_epoch_ns = None
if 'rosbag_start_epoch_ns_a' not in st.session_state:
    st.session_state.rosbag_start_epoch_ns_a = None
if 'rosbag_start_epoch_ns_b' not in st.session_state:
    st.session_state.rosbag_start_epoch_ns_b = None
if 'live_monitor_history' not in st.session_state:
    st.session_state.live_monitor_history = []
if 'auto_refresh_live' not in st.session_state:
    st.session_state.auto_refresh_live = True

st.title("🔴 Lidar Session Manager")

if DEMO_MODE:
    st.warning("🎭 **DEMO MODE ACTIVÉ** - Les données ne sont pas enregistrées réellement. Pour tester l'interface complète.")

# ========== SIDEBAR ==========
with st.sidebar:
    free_b, total_b = get_disk_free(UI_CFG['session_data_root'])
    if free_b is not None:
        pct_free = 100.0 * free_b / total_b if total_b else 0
        disk_msg = f"💾 Espace disque libre : {human_bytes(free_b)} ({pct_free:.0f}%)"
        if pct_free < 10:
            st.error(disk_msg + " — critique, libérez de la place avant d'enregistrer")
        elif pct_free < 20:
            st.warning(disk_msg)
        else:
            st.caption(disk_msg)

    st.header("Configuration")
    ros_mode_available = detect_rosbag_mode()
    data_root = st.text_input("Data Root Dir:", UI_CFG['session_data_root'])
    sensor_a_ip = st.text_input("Sensor A IP:", SENSORS_CFG['sensor_a']['ip'])
    use_sensor_b = False
    sensor_b_ip = ""
    if SENSOR_B_AVAILABLE:
        use_sensor_b = st.checkbox(
            "Activer capteur B",
            value=st.session_state.use_sensor_b,
            disabled=st.session_state.recorder_proc is not None
        )
        sensor_b_ip = st.text_input(
            "Sensor B IP:",
            SENSORS_CFG['sensor_b']['ip'],
            disabled=not use_sensor_b
        )
    else:
        st.caption("Mode 1 capteur: `sensor_b` absent de `configs/sensors.yaml`")
    port = st.number_input("UDP Port:", value=SENSORS_CFG['port'])
    enable_bag = st.checkbox(
        "Enregistrer aussi un .bag (recorder interne)",
        value=st.session_state.enable_bag,
        disabled=st.session_state.recorder_proc is not None,
        help="Format .bag en plus du .pcap habituel — quasi la même taille, donc double l'espace disque utilisé. Désactivé par défaut.",
    )
    enable_rosbag = st.checkbox(
        "Enregistrer RosBag auto (ROS1/ROS2)",
        value=st.session_state.enable_rosbag,
        disabled=(st.session_state.recorder_proc is not None) or (ros_mode_available is None)
    )
    rosbag_topic_a = st.text_input(
        "Topic capteur A",
        value=st.session_state.rosbag_topic_a,
        disabled=(st.session_state.recorder_proc is not None) or (not enable_rosbag)
    )
    rosbag_topic_b = ""
    if SENSOR_B_AVAILABLE:
        rosbag_topic_b = st.text_input(
            "Topic capteur B",
            value=st.session_state.rosbag_topic_b,
            disabled=(st.session_state.recorder_proc is not None) or (not enable_rosbag) or (not use_sensor_b)
        )
    enable_ros_autolaunch = st.checkbox(
        "Auto-lancer commandes ROS",
        value=st.session_state.enable_ros_autolaunch,
        disabled=(st.session_state.recorder_proc is not None) or (not enable_rosbag)
    )
    roscore_cmd = st.text_input(
        "Commande ROS core",
        value=st.session_state.roscore_cmd,
        disabled=(st.session_state.recorder_proc is not None) or (not enable_rosbag) or (not enable_ros_autolaunch)
    )
    ros_driver_a_cmd = st.text_input(
        "Commande driver capteur A",
        value=st.session_state.ros_driver_a_cmd,
        disabled=(st.session_state.recorder_proc is not None) or (not enable_rosbag) or (not enable_ros_autolaunch)
    )
    ros_driver_b_cmd = ""
    if SENSOR_B_AVAILABLE:
        ros_driver_b_cmd = st.text_input(
            "Commande driver capteur B",
            value=st.session_state.ros_driver_b_cmd,
            disabled=(st.session_state.recorder_proc is not None) or (not enable_rosbag) or (not enable_ros_autolaunch) or (not use_sensor_b)
        )
    if ros_mode_available is None:
        st.caption("RosBag non détecté: installe/sourcer ROS1 Noetic ou ROS2.")
    else:
        st.caption(f"Mode RosBag détecté: `{ros_mode_available}`")
    
    # Stockage dans la session pour accès partout
    st.session_state.data_root = data_root
    st.session_state.sensor_a_ip = sensor_a_ip
    st.session_state.use_sensor_b = bool(use_sensor_b and SENSOR_B_AVAILABLE)
    st.session_state.sensor_b_ip = sensor_b_ip
    st.session_state.port = int(port)
    st.session_state.enable_bag = bool(enable_bag)
    st.session_state.enable_rosbag = bool(enable_rosbag and ros_mode_available is not None)
    st.session_state.rosbag_topic_a = rosbag_topic_a
    st.session_state.rosbag_topic_b = rosbag_topic_b
    st.session_state.enable_ros_autolaunch = bool(enable_ros_autolaunch and st.session_state.enable_rosbag)
    st.session_state.roscore_cmd = roscore_cmd
    st.session_state.ros_driver_a_cmd = ros_driver_a_cmd
    st.session_state.ros_driver_b_cmd = ros_driver_b_cmd

# ========== MAIN ==========
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Session Control")
    
    if st.session_state.recorder_proc is None:
        if st.button("▶️ Start Session", use_container_width=True, key="btn_start"):
            use_sensor_b_this_session = bool(st.session_state.use_sensor_b)
            st.session_state.live_monitor_history = []
            st.session_state.recorder_start_epoch_ns = None
            st.session_state.rosbag_start_epoch_ns_a = None
            st.session_state.rosbag_start_epoch_ns_b = None

            # Recorder-only mode for the main Start Session action.
            # ROS bag / ROS autolaunch must be explicitly re-enabled in a separate flow.
            rosbag_enabled_this_session = False
            ros_autolaunch_this_session = False
            rosbag_topics_this_session = [st.session_state.rosbag_topic_a.strip()]
            if use_sensor_b_this_session:
                rosbag_topics_this_session.append(st.session_state.rosbag_topic_b.strip())
            rosbag_topics_this_session = [t for t in rosbag_topics_this_session if t]
            rosbag_mode = detect_rosbag_mode() if rosbag_enabled_this_session else None

            if use_sensor_b_this_session and not st.session_state.sensor_b_ip.strip():
                st.error("❌ Capteur B activé mais IP vide.")
                st.stop()
            if rosbag_enabled_this_session and rosbag_mode is None:
                st.error("❌ RosBag demandé mais ni ROS2 ni ROS1 détecté dans le shell.")
                st.stop()
            if rosbag_enabled_this_session and not rosbag_topics_this_session:
                st.error("❌ RosBag activé mais liste de topics vide.")
                st.stop()
            if rosbag_enabled_this_session and use_sensor_b_this_session and not st.session_state.rosbag_topic_b.strip():
                st.error("❌ RosBag activé avec capteur B, mais topic capteur B vide.")
                st.stop()
            if rosbag_enabled_this_session and ros_autolaunch_this_session and not st.session_state.ros_driver_a_cmd.strip():
                st.error("❌ Auto-lancement activé mais commande driver capteur A vide.")
                st.stop()

            now = datetime.now().strftime('%Y%m%d_%H%M%S')
            session_id = f"S001_P01_{now}"
            base = os.path.join(st.session_state.data_root, session_id)
            
            os.makedirs(os.path.join(base, 'raw', 'pcap'), exist_ok=True)
            if st.session_state.enable_bag:
                os.makedirs(os.path.join(base, 'raw', 'bag'), exist_ok=True)
            os.makedirs(os.path.join(base, 'raw', 'rosbag'), exist_ok=True)
            os.makedirs(os.path.join(base, 'meta'), exist_ok=True)
            os.makedirs(os.path.join(base, 'logs'), exist_ok=True)
            os.makedirs(os.path.join(base, 'derived', 'lidar_A', 'pcd'), exist_ok=True)
            if use_sensor_b_this_session:
                os.makedirs(os.path.join(base, 'derived', 'lidar_B', 'pcd'), exist_ok=True)
            
            # Store session start time for elapsed time tracking
            st.session_state.session_start_epoch_ns = now_epoch_ns()
            st.session_state.session_start_time = datetime.fromtimestamp(st.session_state.session_start_epoch_ns / 1e9)
            st.session_state.session_sensor_b_enabled = use_sensor_b_this_session
            
            meta = {
                'session_id': session_id,
                'lidar_a_ip': st.session_state.sensor_a_ip,
                'lidar_b_ip': st.session_state.sensor_b_ip if use_sensor_b_this_session else None,
                'sensor_b_enabled': use_sensor_b_this_session,
                'raw_pcap_a': os.path.join('raw', 'pcap', 'lidar_A.pcap'),
                'raw_pcap_b': os.path.join('raw', 'pcap', 'lidar_B.pcap') if use_sensor_b_this_session else None,
                'raw_bag_a': os.path.join('raw', 'bag', 'lidar_A.bag') if st.session_state.enable_bag else None,
                'raw_bag_b': os.path.join('raw', 'bag', 'lidar_B.bag') if st.session_state.enable_bag and use_sensor_b_this_session else None,
                'rosbag_enabled': rosbag_enabled_this_session,
                'rosbag_mode': rosbag_mode,
                'rosbag_topics': rosbag_topics_this_session,
                'ros_autolaunch_enabled': ros_autolaunch_this_session,
                'roscore_cmd': st.session_state.roscore_cmd if ros_autolaunch_this_session else None,
                'ros_driver_a_cmd': st.session_state.ros_driver_a_cmd if ros_autolaunch_this_session else None,
                'ros_driver_b_cmd': st.session_state.ros_driver_b_cmd if ros_autolaunch_this_session and use_sensor_b_this_session else None,
                'rosbag_output_a': os.path.join('raw', 'rosbag', 'lidar_A_ros2') if rosbag_enabled_this_session and rosbag_mode == "ros2" else (os.path.join('raw', 'rosbag', 'lidar_A_ros1.bag') if rosbag_enabled_this_session else None),
                'rosbag_output_b': (os.path.join('raw', 'rosbag', 'lidar_B_ros2') if rosbag_mode == "ros2" else os.path.join('raw', 'rosbag', 'lidar_B_ros1.bag')) if rosbag_enabled_this_session and use_sensor_b_this_session else None,
                'rosbag_log_a': os.path.join('logs', 'rosbag_record_a.log') if rosbag_enabled_this_session else None,
                'rosbag_log_b': os.path.join('logs', 'rosbag_record_b.log') if rosbag_enabled_this_session and use_sensor_b_this_session else None,
                'recorder_log': os.path.join('logs', 'recorder.log'),
                'timeline_reference': 'ros' if rosbag_enabled_this_session else 'system',
                'recorder_start_epoch_ns': None,
                'rosbag_start_epoch_ns_a': None,
                'rosbag_start_epoch_ns_b': None,
                'rosbag_offset_ns_a_from_recorder': None,
                'rosbag_offset_ns_b_from_recorder': None,
                'ros_prereq_log': os.path.join('logs', 'ros_prereq.log') if rosbag_enabled_this_session and ros_autolaunch_this_session else None,
                'port': st.session_state.port,
                'interface': SENSORS_CFG.get('interface', 'eth0'),
                'start_epoch_ns': st.session_state.session_start_epoch_ns,
                'start_time': st.session_state.session_start_time.isoformat(),
            }
            with open(os.path.join(base, 'meta', 'session_meta.yaml'), 'w') as f:
                yaml.dump(meta, f)
            
            if DEMO_MODE:
                # Mode démo - crée un processus fictif
                import time
                class DummyProc:
                    def __init__(self):
                        self.pid = 9999
                    def terminate(self):
                        pass
                    def wait(self, timeout=None):
                        pass
                st.session_state.recorder_proc = DummyProc()
                st.session_state.rosbag_proc_a = None
                st.session_state.rosbag_proc_b = None
                st.session_state.roscore_proc = None
                st.session_state.ros_driver_a_proc = None
                st.session_state.ros_driver_b_proc = None
                st.session_state.session_rosbag_mode = rosbag_mode
                st.session_state.session_rosbag_output_a = None
                st.session_state.session_rosbag_output_b = None
                st.session_state.rosbag_log_path_a = os.path.join(base, 'logs', 'rosbag_record_a.log') if rosbag_enabled_this_session else None
                st.session_state.rosbag_log_path_b = os.path.join(base, 'logs', 'rosbag_record_b.log') if rosbag_enabled_this_session and use_sensor_b_this_session else None
                st.session_state.recorder_log_path = os.path.join(base, 'logs', 'recorder.log')
                st.session_state.ros_prereq_log_path = os.path.join(base, 'logs', 'ros_prereq.log') if rosbag_enabled_this_session and ros_autolaunch_this_session else None
                st.session_state.session_base = base
                st.session_state.scenario_log_path = os.path.join(base, 'logs', 'session_log.csv')
                st.session_state.lidar_a_log_path = os.path.join(base, 'logs', 'lidar_A_log.csv')
                st.session_state.lidar_b_log_path = os.path.join(base, 'logs', 'lidar_B_log.csv') if use_sensor_b_this_session else None
                initialize_session_logs(
                    st.session_state.scenario_log_path,
                    st.session_state.lidar_a_log_path,
                    st.session_state.lidar_b_log_path,
                    st.session_state.session_start_epoch_ns,
                    use_sensor_b_this_session,
                )
                
                st.success(f"✅ [DEMO MODE] Session started: {session_id}")
                st.rerun()
            else:
                # Mode réel - lance le recorder
                rec_bin = resolve_recorder_binary()
                if rec_bin is None:
                    st.error("❌ Recorder introuvable. Build attendu dans `recorder/recorder` ou `recorder/build/recorder`.")
                    st.stop()
                out_dir = os.path.join(base, 'raw', 'pcap')
                rosbag_dir = os.path.join(base, 'raw', 'rosbag')
                pcap_a = 'lidar_A.pcap'
                cmd = [rec_bin, 'record', '--out_dir', out_dir, '--pcap_a', pcap_a,
                       '--port', str(st.session_state.port),
                       '--ip_a', st.session_state.sensor_a_ip,
                       '--timestamp_source', 'kernel']
                if st.session_state.enable_bag:
                    bag_dir = os.path.join(base, 'raw', 'bag')
                    cmd.extend(['--bag_dir', bag_dir, '--bag_a', 'lidar_A.bag', '--enable_bag'])
                iface = str(SENSORS_CFG.get('interface', '')).strip()
                if iface:
                    cmd.extend(['--interface', iface])
                if use_sensor_b_this_session and st.session_state.sensor_b_ip:
                    cmd.extend(['--ip_b', st.session_state.sensor_b_ip, '--pcap_b', 'lidar_B.pcap'])
                    if st.session_state.enable_bag:
                        cmd.extend(['--bag_b', 'lidar_B.bag'])
                
                try:
                    recorder_log_path = os.path.join(base, 'logs', 'recorder.log')
                    st.session_state.recorder_log_path = recorder_log_path
                    st.session_state.recorder_start_epoch_ns = now_epoch_ns()
                    with open(recorder_log_path, 'ab') as recorder_log_file:
                        st.session_state.recorder_proc = subprocess.Popen(
                            cmd,
                            stdout=recorder_log_file,
                            stderr=recorder_log_file,
                            preexec_fn=os.setsid
                        )
                    update_session_meta(
                        base,
                        {
                            'recorder_start_epoch_ns': st.session_state.recorder_start_epoch_ns,
                            'timeline_reference': 'ros' if rosbag_enabled_this_session else 'system',
                        },
                    )
                    st.session_state.rosbag_proc_a = None
                    st.session_state.rosbag_proc_b = None
                    st.session_state.session_rosbag_mode = None
                    st.session_state.session_rosbag_output_a = None
                    st.session_state.session_rosbag_output_b = None
                    st.session_state.rosbag_log_path_a = None
                    st.session_state.rosbag_log_path_b = None
                    st.session_state.ros_prereq_log_path = None
                    st.session_state.roscore_proc = None
                    st.session_state.ros_driver_a_proc = None
                    st.session_state.ros_driver_b_proc = None

                    if rosbag_enabled_this_session and ros_autolaunch_this_session:
                        prereq_log_path = os.path.join(base, 'logs', 'ros_prereq.log')
                        st.session_state.ros_prereq_log_path = prereq_log_path
                        if rosbag_mode == "ros1":
                            st.session_state.roscore_proc = launch_bg_command(st.session_state.roscore_cmd, prereq_log_path)
                            time.sleep(1.0)
                        st.session_state.ros_driver_a_proc = launch_bg_command(st.session_state.ros_driver_a_cmd, prereq_log_path)
                        if use_sensor_b_this_session and st.session_state.ros_driver_b_cmd.strip():
                            st.session_state.ros_driver_b_proc = launch_bg_command(st.session_state.ros_driver_b_cmd, prereq_log_path)
                        time.sleep(2.0)

                    if rosbag_enabled_this_session:
                        preflight_ok, preflight_msg = preflight_ros(rosbag_mode, rosbag_topics_this_session)
                        if not preflight_ok:
                            raise RuntimeError(f"Pré-vol RosBag échoué: {preflight_msg}")

                    if rosbag_enabled_this_session:
                        rosbag_cmd_a, rosbag_output_a = build_rosbag_command(
                            rosbag_mode, rosbag_dir, "A", st.session_state.rosbag_topic_a.strip()
                        )
                        rosbag_log_path_a = os.path.join(base, 'logs', 'rosbag_record_a.log')
                        st.session_state.rosbag_start_epoch_ns_a = now_epoch_ns()
                        with open(rosbag_log_path_a, 'ab') as rosbag_log_file_a:
                            st.session_state.rosbag_proc_a = subprocess.Popen(
                                rosbag_cmd_a,
                                stdout=rosbag_log_file_a,
                                stderr=rosbag_log_file_a,
                                preexec_fn=os.setsid
                            )
                        st.session_state.session_rosbag_output_a = rosbag_output_a
                        st.session_state.rosbag_log_path_a = rosbag_log_path_a

                        if use_sensor_b_this_session:
                            rosbag_cmd_b, rosbag_output_b = build_rosbag_command(
                                rosbag_mode, rosbag_dir, "B", st.session_state.rosbag_topic_b.strip()
                            )
                            rosbag_log_path_b = os.path.join(base, 'logs', 'rosbag_record_b.log')
                            st.session_state.rosbag_start_epoch_ns_b = now_epoch_ns()
                            with open(rosbag_log_path_b, 'ab') as rosbag_log_file_b:
                                st.session_state.rosbag_proc_b = subprocess.Popen(
                                    rosbag_cmd_b,
                                    stdout=rosbag_log_file_b,
                                    stderr=rosbag_log_file_b,
                                    preexec_fn=os.setsid
                                )
                            st.session_state.session_rosbag_output_b = rosbag_output_b
                            st.session_state.rosbag_log_path_b = rosbag_log_path_b

                        time.sleep(1.0)
                        if st.session_state.rosbag_proc_a and st.session_state.rosbag_proc_a.poll() is not None:
                            raise RuntimeError(
                                f"RosBag A ended early. Check log: {rosbag_log_path_a}"
                            )
                        if st.session_state.rosbag_proc_b and st.session_state.rosbag_proc_b.poll() is not None:
                            raise RuntimeError(
                                f"RosBag B ended early. Check log: {rosbag_log_path_b}"
                            )
                        st.session_state.session_rosbag_mode = rosbag_mode
                        recorder_start = st.session_state.recorder_start_epoch_ns
                        offset_a = None
                        offset_b = None
                        if recorder_start and st.session_state.rosbag_start_epoch_ns_a:
                            offset_a = st.session_state.rosbag_start_epoch_ns_a - recorder_start
                        if recorder_start and st.session_state.rosbag_start_epoch_ns_b:
                            offset_b = st.session_state.rosbag_start_epoch_ns_b - recorder_start
                        update_session_meta(
                            base,
                            {
                                'timeline_reference': 'ros',
                                'recorder_start_epoch_ns': recorder_start,
                                'rosbag_start_epoch_ns_a': st.session_state.rosbag_start_epoch_ns_a,
                                'rosbag_start_epoch_ns_b': st.session_state.rosbag_start_epoch_ns_b,
                                'rosbag_offset_ns_a_from_recorder': offset_a,
                                'rosbag_offset_ns_b_from_recorder': offset_b,
                            },
                        )

                    st.session_state.session_base = base
                    st.session_state.scenario_log_path = os.path.join(base, 'logs', 'session_log.csv')
                    st.session_state.lidar_a_log_path = os.path.join(base, 'logs', 'lidar_A_log.csv')
                    st.session_state.lidar_b_log_path = os.path.join(base, 'logs', 'lidar_B_log.csv') if use_sensor_b_this_session else None
                    initialize_session_logs(
                        st.session_state.scenario_log_path,
                        st.session_state.lidar_a_log_path,
                        st.session_state.lidar_b_log_path,
                        st.session_state.session_start_epoch_ns,
                        use_sensor_b_this_session,
                    )
                    
                    st.success(f"✅ Session started: {session_id}")
                    st.rerun()
                except Exception as e:
                    stop_process_group(st.session_state.rosbag_proc_b)
                    stop_process_group(st.session_state.rosbag_proc_a)
                    stop_process_group(st.session_state.ros_driver_b_proc)
                    stop_process_group(st.session_state.ros_driver_a_proc)
                    stop_process_group(st.session_state.roscore_proc)
                    stop_process_group(st.session_state.recorder_proc)
                    reset_runtime_state(clear_session_context=False)
                    st.error(f"❌ Failed to start: {e}")
    else:
        if st.button("⏹️ Stop Session", use_container_width=True, key="btn_stop"):
            try:
                stop_process_group(st.session_state.rosbag_proc_b)
                stop_process_group(st.session_state.rosbag_proc_a)
                stop_process_group(st.session_state.ros_driver_b_proc)
                stop_process_group(st.session_state.ros_driver_a_proc)
                stop_process_group(st.session_state.roscore_proc)
                stop_process_group(st.session_state.recorder_proc)
                st.session_state.rosbag_proc_a = None
                st.session_state.rosbag_proc_b = None
                st.session_state.ros_driver_b_proc = None
                st.session_state.ros_driver_a_proc = None
                st.session_state.roscore_proc = None
                with open(st.session_state.scenario_log_path, 'a') as f:
                    epoch_ns = now_epoch_ns()
                    elapsed = int((epoch_ns - st.session_state.session_start_epoch_ns) / 1_000_000_000)
                    lidar_b_status = "ok" if st.session_state.session_sensor_b_enabled else "disabled"
                    f.write(f"session_end,{fmt_hms_from_ns(epoch_ns)},{elapsed},{epoch_ns},ok,{lidar_b_status}\n")
                st.success("✅ Session stopped")
                reset_runtime_state(clear_session_context=True)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Failed to stop: {e}")

with col2:
    st.subheader("Session Status")
    if st.session_state.recorder_proc:
        col_status, col_time = st.columns(2)
        with col_status:
            st.metric("Status", "🟢 Recording", "Active")
        with col_time:
            st.metric("Session ID", os.path.basename(st.session_state.session_base) if st.session_state.session_base else "—", "")
        st.info(f"📂 Path: {st.session_state.session_base}")
        if st.session_state.session_rosbag_mode and st.session_state.session_rosbag_output_a:
            st.caption(f"RosBag A actif: `{st.session_state.session_rosbag_mode}` -> `{st.session_state.session_rosbag_output_a}`")
        if st.session_state.session_rosbag_mode and st.session_state.session_rosbag_output_b:
            st.caption(f"RosBag B actif: `{st.session_state.session_rosbag_mode}` -> `{st.session_state.session_rosbag_output_b}`")
        if st.session_state.rosbag_log_path_a:
            st.caption(f"Log RosBag A: `{st.session_state.rosbag_log_path_a}`")
        if st.session_state.rosbag_log_path_b:
            st.caption(f"Log RosBag B: `{st.session_state.rosbag_log_path_b}`")
        if st.session_state.recorder_log_path:
            st.caption(f"Log Recorder: `{st.session_state.recorder_log_path}`")
        if st.session_state.ros_prereq_log_path:
            st.caption(f"Log ROS prereq: `{st.session_state.ros_prereq_log_path}`")
    else:
        st.metric("Status", "🔴 Stopped", "Idle")

    if st.session_state.recorder_proc and st.session_state.session_base:
        st.divider()
        st.subheader("Live Sensor Monitor")
        st.session_state.auto_refresh_live = st.checkbox(
            "Auto-refresh monitor (2s)",
            value=st.session_state.auto_refresh_live,
            key="live_monitor_autorefresh",
        )

        base = st.session_state.session_base
        pcap_a_path = os.path.join(base, "raw", "pcap", "lidar_A.pcap")
        pcap_b_path = os.path.join(base, "raw", "pcap", "lidar_B.pcap")
        rosbag_a_dir = os.path.join(base, "raw", "rosbag", "lidar_A_ros2")
        rosbag_b_dir = os.path.join(base, "raw", "rosbag", "lidar_B_ros2")
        # Prefer the counters the recorder already computed and logged (cheap: a
        # regex over a small text file) over count_pcap_packets, which re-parses
        # every record of the raw pcap byte-by-byte in Python — fine for a small
        # file, but a multi-GB pcap makes it slow enough to make the whole page
        # feel heavy on every 2s auto-refresh. Only fall back to the full scan
        # when the log-based counters aren't available yet (e.g. just started).
        counters = parse_recorder_counters(st.session_state.recorder_log_path)

        if counters:
            packets_a = counters["a"]
            packets_b = counters["b"]
        else:
            packets_a = count_pcap_packets(pcap_a_path)
            packets_b = count_pcap_packets(pcap_b_path)
        dropped_ip = counters["dropped"] if counters else 0
        now_ts = time.time()
        st.session_state.live_monitor_history.append(
            {"ts": now_ts, "a": packets_a, "b": packets_b}
        )
        st.session_state.live_monitor_history = st.session_state.live_monitor_history[-120:]
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Capteur A**")
            st.metric("Packets", f"{packets_a:,}")
            st.metric("PCAP size", human_bytes(get_file_size(pcap_a_path)))
            st.metric("RosBag size", human_bytes(get_dir_size(rosbag_a_dir)))
        with col_b:
            st.markdown("**Capteur B**")
            st.metric("Packets", f"{packets_b:,}")
            st.metric("PCAP size", human_bytes(get_file_size(pcap_b_path)))
            st.metric("RosBag size", human_bytes(get_dir_size(rosbag_b_dir)))

        st.caption(f"Recorder dropped_ip: {dropped_ip}")
        if len(st.session_state.live_monitor_history) > 1:
            chart_data = {
                "A packets": [x["a"] for x in st.session_state.live_monitor_history],
                "B packets": [x["b"] for x in st.session_state.live_monitor_history],
            }
            st.line_chart(chart_data)

# ========== SCENARIOS ==========
st.divider()
st.subheader("Scénarios")

session_active = bool(
    st.session_state.recorder_proc is not None
    or (st.session_state.session_base and os.path.isdir(st.session_state.session_base))
)

if session_active:
    # Build scenario options grouped by category
    scenario_dict = {s['id']: s for s in SCENARIOS_CFG['scenarios']}
    categories = {}
    for scenario in SCENARIOS_CFG['scenarios']:
        cat = scenario.get('category', 'Autre')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(scenario)

    # Create formatted options with category
    scenario_options = [("-- Sélectionner un scénario --", None)]  # Option vide par défaut
    for cat in sorted(categories.keys()):
        for s in categories[cat]:
            label = f"[{s['id']}] {s['label']} ({s.get('difficulty', 'N/A')})"
            scenario_options.append((label, s['id']))

    open_scenario = find_open_scenario(st.session_state.lidar_a_log_path)

    completion_counts = scenario_completion_counts(st.session_state.lidar_a_log_path)
    done_count = sum(1 for s in SCENARIOS_CFG['scenarios'] if completion_counts.get(s['id']))
    with st.expander(f"📋 Scénarios complétés cette session ({done_count}/{len(SCENARIOS_CFG['scenarios'])})"):
        for s in SCENARIOS_CFG['scenarios']:
            n = completion_counts.get(s['id'], 0)
            mark = "✅" if n else "⬜"
            suffix = f" — {n} prise(s)" if n else ""
            st.caption(f"{mark} [{s['id']}] {s['label']}{suffix}")

    if open_scenario:
        open_id, open_ts = open_scenario
        open_label = next((lbl for lbl, sid in scenario_options if sid == open_id), open_id)
        st.warning(f"🔴 Scénario en cours : **{open_label}** — démarré à {fmt_hms_from_ns(int(open_ts))}. "
                   f"Cliquez Stop Scenario avant d'en choisir un autre.")
        default_index = next((i for i, (_, sid) in enumerate(scenario_options) if sid == open_id), 0)
    else:
        default_index = 0

    scenario_display = [opt[0] for opt in scenario_options]
    selected_scenario_label = st.selectbox(
        "Choisir un scénario:", scenario_display,
        index=default_index, key="scenario_select", disabled=bool(open_scenario),
    )
    scenario_id = [opt[1] for opt in scenario_options if opt[0] == selected_scenario_label][0]

    # Only proceed if a scenario is selected
    if scenario_id:
        # Get scenario details
        selected_scenario_data = scenario_dict[scenario_id]
        
        # Display scenario info
        col_info1, col_info2, col_info3 = st.columns(3)
        with col_info1:
            st.metric("Catégorie", selected_scenario_data.get('category', 'N/A'))
        with col_info2:
            st.metric("Difficulté", selected_scenario_data.get('difficulty', 'N/A'))
        with col_info3:
            st.metric("Zone(s)", selected_scenario_data.get('zone', 'N/A'))
        
        col1, col2 = st.columns(2)
        with col1:
            zone = st.text_input("Zone:", placeholder="ex: Z1, Z2")
            num_people = st.number_input("Nombre de personnes:", min_value=1, value=int(selected_scenario_data.get('num_people', 1)))
        with col2:
            occlusion = st.selectbox("Occlusion:", ["none", "partial", "full"])
            notes = st.text_input("Notes:", placeholder="Notes optionnelles")
        
        col_start, col_stop = st.columns(2)
        with col_start:
            if st.button("▶️ Start Scenario", use_container_width=True, key="btn_start_scenario",
                         disabled=bool(open_scenario)):
                scenario_label_full = selected_scenario_data['label']
                epoch_ns_a = now_epoch_ns()
                with open(st.session_state.lidar_a_log_path, 'a', newline='') as f:
                    elapsed = int((epoch_ns_a - st.session_state.session_start_epoch_ns) / 1_000_000_000)
                    csv.writer(f).writerow(["scenario_start", fmt_hms_from_ns(epoch_ns_a), elapsed, epoch_ns_a,
                                             scenario_id, scenario_label_full, zone, num_people, occlusion, notes, "ok"])
                if st.session_state.lidar_b_log_path:
                    epoch_ns_b = now_epoch_ns()
                    with open(st.session_state.lidar_b_log_path, 'a', newline='') as f:
                        elapsed = int((epoch_ns_b - st.session_state.session_start_epoch_ns) / 1_000_000_000)
                        csv.writer(f).writerow(["scenario_start", fmt_hms_from_ns(epoch_ns_b), elapsed, epoch_ns_b,
                                                 scenario_id, scenario_label_full, zone, num_people, occlusion, notes, "ok"])
                st.success(f"✅ {selected_scenario_label} started")
                st.rerun()

        with col_stop:
            if st.button("⏹️ Stop Scenario", use_container_width=True, key="btn_stop_scenario",
                         disabled=not bool(open_scenario)):
                scenario_label_full = selected_scenario_data['label']
                epoch_ns_a = now_epoch_ns()
                with open(st.session_state.lidar_a_log_path, 'a', newline='') as f:
                    elapsed = int((epoch_ns_a - st.session_state.session_start_epoch_ns) / 1_000_000_000)
                    csv.writer(f).writerow(["scenario_end", fmt_hms_from_ns(epoch_ns_a), elapsed, epoch_ns_a,
                                             scenario_id, scenario_label_full, zone, num_people, occlusion, notes, "ok"])
                epoch_ns_b = None
                if st.session_state.lidar_b_log_path:
                    epoch_ns_b = now_epoch_ns()
                    with open(st.session_state.lidar_b_log_path, 'a', newline='') as f:
                        elapsed = int((epoch_ns_b - st.session_state.session_start_epoch_ns) / 1_000_000_000)
                        csv.writer(f).writerow(["scenario_end", fmt_hms_from_ns(epoch_ns_b), elapsed, epoch_ns_b,
                                                 scenario_id, scenario_label_full, zone, num_people, occlusion, notes, "ok"])

                # Read start/end back from the log files just written, rather than
                # session_state: the live-monitor auto-refresh (below) reruns this
                # script every 2s while a session is active, which can race with
                # session_state set by the Start Scenario click across reruns.
                base = st.session_state.session_base

                intervals_a = pcap_to_pcd.load_scenario_intervals(st.session_state.lidar_a_log_path)
                matches_a = [iv for iv in intervals_a if iv[2] == scenario_id]
                if matches_a and base:
                    start_ns_a, end_ns_a, _ = matches_a[-1]
                    pcap_a = os.path.join(base, 'raw', 'pcap', 'lidar_A.pcap')
                    out_dir_a = os.path.join(base, 'derived', 'lidar_A', 'pcd')
                    log_path = os.path.join(base, 'logs', 'process_scenario.log')

                    cmd = [sys.executable, os.path.join(PROJECT_ROOT, 'scripts', 'process_scenario.py'),
                           '--scenario_id', scenario_id,
                           '--pcap_a', pcap_a, '--out_dir_a', out_dir_a,
                           '--start_ns_a', str(start_ns_a), '--end_ns_a', str(end_ns_a)]

                    has_b = False
                    if st.session_state.lidar_b_log_path:
                        intervals_b = pcap_to_pcd.load_scenario_intervals(st.session_state.lidar_b_log_path)
                        matches_b = [iv for iv in intervals_b if iv[2] == scenario_id]
                        if matches_b:
                            has_b = True
                            start_ns_b, end_ns_b, _ = matches_b[-1]
                            pcap_b = os.path.join(base, 'raw', 'pcap', 'lidar_B.pcap')
                            out_dir_b = os.path.join(base, 'derived', 'lidar_B', 'pcd')
                            sync_out = os.path.join(base, 'derived', f'sync_{scenario_id}.csv')
                            cmd += ['--pcap_b', pcap_b, '--out_dir_b', out_dir_b,
                                    '--start_ns_b', str(start_ns_b), '--end_ns_b', str(end_ns_b),
                                    '--sync_out', sync_out]

                    # Runs the whole pipeline (PCD + pcap for A, then B, then
                    # timestamp sync) as one detached background process, so
                    # the button click returns immediately and the sync step
                    # is guaranteed to run only after both sensors are done.
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    log_f = open(log_path, 'a')
                    subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)

                    if has_b:
                        st.info(f"🟢🔵 {scenario_id}: extraction PCD + pcap (A et B) puis synchronisation "
                                f"lancées en arrière-plan (voir {log_path})")
                    else:
                        st.info(f"🟢 lidar_A / {scenario_id}: extraction PCD + pcap lancée en arrière-plan (voir {log_path})")
                st.success("✅ Scenario stopped")
                st.rerun()

        pipeline_log = os.path.join(st.session_state.session_base, 'logs', 'process_scenario.log') if st.session_state.session_base else None
        if pipeline_log and os.path.exists(pipeline_log):
            last_lines = tail_lines(pipeline_log, n=6)
            last_text = "\n".join(last_lines)
            if "ATTENTION" in last_text or "Traceback" in last_text or "Error" in last_text:
                status_icon = "⚠️"
            elif any("synchronisation OK" in l or "pas d'etape de synchronisation" in l for l in last_lines):
                status_icon = "✅"
            else:
                status_icon = "⏳"
            with st.expander(f"{status_icon} Statut du pipeline en arrière-plan (extraction + synchro)"):
                st.code(last_text or "(vide)", language="text")
    else:
        st.info("👈 Veuillez sélectionner un scénario")
else:
    st.warning("⚠️ Démarrez d'abord une session")

# ========== LOGS ==========
st.divider()
st.subheader("Logs")

if st.session_state.scenario_log_path or session_active:
    tab_labels = ["📋 Session Log", "🔴 Lidar A Log"]
    if st.session_state.lidar_b_log_path:
        tab_labels.append("🔵 Lidar B Log")
    tabs = st.tabs(tab_labels)
    
    # Session Log tab
    with tabs[0]:
        if os.path.exists(st.session_state.scenario_log_path):
            with open(st.session_state.scenario_log_path, 'r') as f:
                session_logs = f.read()
            st.code(session_logs, language="csv")
            st.download_button("⬇️ Download Session Log", session_logs, "session_log.csv", "text/csv", key="btn_dl_session")
        else:
            st.info("Session log not yet available")
    
    # Lidar A Log tab
    with tabs[1]:
        if os.path.exists(st.session_state.lidar_a_log_path):
            with open(st.session_state.lidar_a_log_path, 'r') as f:
                lidar_a_logs = f.read()
            st.code(lidar_a_logs, language="csv")
            st.download_button("⬇️ Download Lidar A Log", lidar_a_logs, "lidar_A_log.csv", "text/csv", key="btn_dl_lidar_a")
        else:
            st.info("Lidar A log not yet available")
    
    # Lidar B Log tab (si activé)
    if st.session_state.lidar_b_log_path:
        with tabs[2]:
            if os.path.exists(st.session_state.lidar_b_log_path):
                with open(st.session_state.lidar_b_log_path, 'r') as f:
                    lidar_b_logs = f.read()
                st.code(lidar_b_logs, language="csv")
                st.download_button("⬇️ Download Lidar B Log", lidar_b_logs, "lidar_B_log.csv", "text/csv", key="btn_dl_lidar_b")
            else:
                st.info("Lidar B log not yet available")
else:
    st.info("No session logs yet")

# ========== FOOTER ==========
st.divider()
st.caption("Lidar Session Manager v1.0 | Powered by Streamlit")

# Auto-refresh goes last, after the whole page (including Scénarios and Logs)
# has rendered — doing this earlier in the script meant st.rerun() aborted
# the run before those sections were ever reached, making them unusable
# whenever a session was active (auto-refresh defaults to on).
if st.session_state.recorder_proc and st.session_state.session_base and st.session_state.auto_refresh_live:
    time.sleep(2)
    st.rerun()
