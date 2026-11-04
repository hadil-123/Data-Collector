#!/usr/bin/env python3
"""Open live playback of lidar_A and lidar_B for the same scenario at the
same time, in two separate windows, so you can compare both sensors'
coverage of one take right after a collection.

Just launches two `play_pcd_sequence.py` instances (one per sensor) as
subprocesses and waits for both windows to be closed.

Usage:
    scripts/play_scenario_dual.py --session SESSION_DIR --scenario_id D1 \\
        [--interval_ms 100] [--color_by intensity]
"""
import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="Session base directory (contains derived/lidar_A, derived/lidar_B)")
    parser.add_argument("--scenario_id", required=True, help="Scenario id, e.g. D1, A2, M3")
    parser.add_argument("--interval_ms", type=float, default=100.0)
    parser.add_argument("--color_by", default="intensity")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    player = os.path.join(script_dir, "play_pcd_sequence.py")

    dir_a = os.path.join(args.session, "derived", "lidar_A", "pcd", args.scenario_id)
    dir_b = os.path.join(args.session, "derived", "lidar_B", "pcd", args.scenario_id)

    missing = [d for d in (dir_a, dir_b) if not os.path.isdir(d)]
    if missing:
        for d in missing:
            print(f"[play_scenario_dual] introuvable: {d}")
        raise SystemExit(1)

    common = ["--interval_ms", str(args.interval_ms), "--color_by", args.color_by]
    proc_a = subprocess.Popen([sys.executable, player, "--dir", dir_a] + common)
    proc_b = subprocess.Popen([sys.executable, player, "--dir", dir_b] + common)

    print(f"[play_scenario_dual] Capteur A: {dir_a}")
    print(f"[play_scenario_dual] Capteur B: {dir_b}")
    print("[play_scenario_dual] fermez les deux fenetres pour terminer")

    proc_a.wait()
    proc_b.wait()


if __name__ == "__main__":
    main()
