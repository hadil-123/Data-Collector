#!/usr/bin/env python3
"""Open one scenario's lidar_A (and lidar_B, if that pcap exists) .pcap in
VeloView window(s), already loaded with the right calibration (no need to go
through File > Open PCAP File manually for each one).

Technique: VeloView's own `--script`/`--state` startup hooks run before its
Velodyne-specific PythonQt classes are registered (importing
lidarview.applogic that early segfaults/crashes). So each generated script
defers the actual `import lidarview.applogic as VVApp; VVApp.openPcap(...)`
call by a few seconds via a QTimer, which runs once VeloView has finished
starting up.

Usage:
    scripts/open_scenario_veloview.py --session SESSION_DIR --scenario_id D1

    scripts/open_scenario_veloview.py --session SESSION_DIR --scenario_id D1 \\
        --veloview_bin /path/to/VeloView --calibration /path/to/VLP-32c.xml
"""
import argparse
import os
import subprocess
import sys
import tempfile

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_CONFIG_PATH = os.path.join(PROJECT_ROOT, 'configs', 'tools.yaml')

# Used only if configs/tools.yaml is missing or doesn't set these keys.
FALLBACK_VELOVIEW_BIN = (
    "/home/local/USHERBROOKE/elth7585/Téléchargements/"
    "VeloView-5.1.0-Ubuntu18.04-x86_64/bin/VeloView"
)
FALLBACK_CALIBRATION = (
    "/home/local/USHERBROOKE/elth7585/Téléchargements/"
    "VeloView-5.1.0-Ubuntu18.04-x86_64/share/VLP-32c.xml"
)


def load_tools_config():
    try:
        with open(TOOLS_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except OSError:
        cfg = {}
    veloview = cfg.get('veloview') if isinstance(cfg.get('veloview'), dict) else {}
    return {
        'veloview_bin': veloview.get('bin', FALLBACK_VELOVIEW_BIN),
        'calibration': veloview.get('calibration', FALLBACK_CALIBRATION),
    }

STARTUP_SCRIPT_TEMPLATE = """\
from PythonQt.QtCore import QTimer

pcap = {pcap!r}
calib = {calib!r}

def _do_open():
    import lidarview.applogic as VVApp
    VVApp.openPcap(pcap, calib)
    VVApp.onPlay()

QTimer.singleShot(3000, _do_open)
"""


def pcap_name_for_take(scenario_id, take):
    """<id>.pcap pour la 1ere prise, <id>_2.pcap/_3.pcap/... ensuite — doit
    matcher la convention de nommage de pcap_to_pcd.extract_scenario()."""
    return scenario_id if take <= 1 else f"{scenario_id}_{take}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="Session base directory (contains derived/lidar_A, derived/lidar_B)")
    parser.add_argument("--scenario_id", required=True, help="Scenario id, e.g. D1, A2, M3")
    parser.add_argument("--take", type=int, default=1,
                         help="Which take/prise of this scenario to open (1-based) — a scenario_id repeated "
                              "several times in one session produces <id>.pcap, <id>_2.pcap, <id>_3.pcap, ... "
                              "matching the order used by pcap_to_pcd.py's overwrite-protection naming")
    tools_cfg = load_tools_config()
    parser.add_argument("--veloview_bin", default=tools_cfg['veloview_bin'])
    parser.add_argument("--calibration", default=tools_cfg['calibration'])
    args = parser.parse_args()

    if not os.path.isfile(args.veloview_bin):
        raise SystemExit(f"VeloView introuvable: {args.veloview_bin} (utilisez --veloview_bin)")
    if not os.path.isfile(args.calibration):
        raise SystemExit(f"Fichier de calibration introuvable: {args.calibration} (utilisez --calibration)")

    pcap_name = pcap_name_for_take(args.scenario_id, args.take)
    pcap_a = os.path.join(args.session, "derived", "lidar_A", "pcap", f"{pcap_name}.pcap")
    pcap_b = os.path.join(args.session, "derived", "lidar_B", "pcap", f"{pcap_name}.pcap")

    if not os.path.isfile(pcap_a):
        print(f"[open_scenario_veloview] introuvable: {pcap_a}")
        raise SystemExit(1)

    # lidar_B est optionnel: une session mono-capteur n'a pas de pcap B pour
    # ce scenario — on ouvre alors seulement le capteur A au lieu d'echouer.
    sensors = [("A", pcap_a)]
    if os.path.isfile(pcap_b):
        sensors.append(("B", pcap_b))
    else:
        print(f"[open_scenario_veloview] pas de capteur B pour cette prise ({pcap_b} introuvable) — ouverture du capteur A seul")

    procs = []
    tmp_scripts = []
    for label, pcap in sensors:
        script_text = STARTUP_SCRIPT_TEMPLATE.format(pcap=pcap, calib=args.calibration)
        fd, tmp_path = tempfile.mkstemp(suffix=f"_open_{label}.py", prefix="veloview_")
        with os.fdopen(fd, "w") as f:
            f.write(script_text)
        tmp_scripts.append(tmp_path)
        print(f"[open_scenario_veloview] Capteur {label}: {pcap}")
        procs.append(subprocess.Popen([args.veloview_bin, f"--script={tmp_path}"]))

    window_word = "la fenetre" if len(procs) == 1 else "les fenetres"
    print(f"[open_scenario_veloview] fermez {window_word} VeloView pour terminer")
    for proc in procs:
        proc.wait()
    for tmp_path in tmp_scripts:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
