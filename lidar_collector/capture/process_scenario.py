#!/usr/bin/env python3
"""Full per-scenario pipeline, run as a single process so steps happen in
the right order: extract PCD+pcap for lidar_A, then lidar_B (if given), then
pair their frames by timestamp. The webui launches this once per
Stop Scenario click as one detached background process, so the sync step
reliably runs only after both sensors' extraction has actually finished.

Usage (dual-sensor):
    scripts/process_scenario.py --scenario_id D2 \\
        --pcap_a SESSION/raw/pcap/lidar_A.pcap --out_dir_a SESSION/derived/lidar_A/pcd \\
        --start_ns_a 169000... --end_ns_a 169000... \\
        --pcap_b SESSION/raw/pcap/lidar_B.pcap --out_dir_b SESSION/derived/lidar_B/pcd \\
        --start_ns_b 169000... --end_ns_b 169000... \\
        --sync_out SESSION/derived/sync_D2.csv

Usage (single-sensor, no --pcap_b): just extracts lidar_A, no sync step.
"""
import argparse
import os

from lidar_collector.capture import pcap_to_pcd
from lidar_collector.capture import sync_scenario_frames


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario_id", required=True)
    p.add_argument("--pcap_a", required=True)
    p.add_argument("--out_dir_a", required=True)
    p.add_argument("--start_ns_a", type=int, required=True)
    p.add_argument("--end_ns_a", type=int, required=True)
    p.add_argument("--pcap_b", default=None)
    p.add_argument("--out_dir_b", default=None)
    p.add_argument("--start_ns_b", type=int, default=None)
    p.add_argument("--end_ns_b", type=int, default=None)
    p.add_argument("--sync_out", default=None)
    p.add_argument("--model", default="VLP32C")
    args = p.parse_args()

    n_frames_a, n_pkts_a, pcap_out_a = pcap_to_pcd.extract_scenario(
        args.pcap_a, args.out_dir_a, args.scenario_id, args.start_ns_a, args.end_ns_a, model=args.model)
    print(f"[process_scenario] lidar_A: {n_frames_a} frames, {n_pkts_a} paquets -> {pcap_out_a}")

    if not args.pcap_b:
        print("[process_scenario] pas de capteur B fourni — pas d'etape de synchronisation")
        return

    n_frames_b, n_pkts_b, pcap_out_b = pcap_to_pcd.extract_scenario(
        args.pcap_b, args.out_dir_b, args.scenario_id, args.start_ns_b, args.end_ns_b, model=args.model)
    print(f"[process_scenario] lidar_B: {n_frames_b} frames, {n_pkts_b} paquets -> {pcap_out_b}")

    manifest_a = os.path.join(args.out_dir_a, args.scenario_id, "manifest.csv")
    manifest_b = os.path.join(args.out_dir_b, args.scenario_id, "manifest.csv")
    sync_out = args.sync_out or os.path.join(os.path.dirname(os.path.normpath(args.out_dir_a)), "..", f"sync_{args.scenario_id}.csv")
    n_pairs, flagged = sync_scenario_frames.sync_manifests(manifest_a, manifest_b, sync_out)
    print(f"[process_scenario] synchro: {n_pairs} paires -> {sync_out}")
    if flagged:
        print(f"[process_scenario] ATTENTION: {flagged} paire(s) avec un ecart anormal (frame probablement manquante d'un cote)")
    else:
        print("[process_scenario] synchronisation OK, aucun ecart anormal")


if __name__ == "__main__":
    main()
