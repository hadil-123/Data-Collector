"""Reading/writing the per-session CSV logs (session_log.csv, lidar_*_log.csv)
and the session_meta.yaml sidecar file."""
import csv
import os

import yaml

from lidar_collector.session.paths import fmt_hms_from_ns


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
