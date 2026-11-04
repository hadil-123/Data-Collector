#!/usr/bin/env python3
"""Pair up lidar_A and lidar_B frames of the same scenario by nearest timestamp.

Both sensors are timestamped by the same recorder process on the same host
clock (epoch_ns), so their manifest.csv files are already directly
comparable — this just does the nearest-neighbor matching and writes one
combined table instead of two separate ones.

Usage:
    scripts/sync_scenario_frames.py \\
        --manifest_a SESSION/derived/lidar_A/pcd/D2/manifest.csv \\
        --manifest_b SESSION/derived/lidar_B/pcd/D2/manifest.csv \\
        --out SESSION/derived/sync_D2.csv \\
        [--max_delta_ms 70]
"""
import argparse
import csv


def load_manifest(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["epoch_ns"] = int(r["epoch_ns"])
    rows.sort(key=lambda r: r["epoch_ns"])
    return rows


def pair_nearest(rows_a, rows_b):
    """For each A frame, find the B frame with the closest epoch_ns.
    Two-pointer scan since both lists are time-sorted."""
    pairs = []
    j = 0
    for a in rows_a:
        while j + 1 < len(rows_b) and abs(rows_b[j + 1]["epoch_ns"] - a["epoch_ns"]) <= abs(rows_b[j]["epoch_ns"] - a["epoch_ns"]):
            j += 1
        b = rows_b[j] if rows_b else None
        pairs.append((a, b))
    return pairs


def sync_manifests(manifest_a_path, manifest_b_path, out_path, max_delta_ms=70.0):
    """Pair lidar_A/lidar_B frames by nearest timestamp and write the combined
    CSV. Returns (n_pairs, n_flagged)."""
    rows_a = load_manifest(manifest_a_path)
    rows_b = load_manifest(manifest_b_path)
    if not rows_a or not rows_b:
        raise ValueError("One of the manifests is empty")

    pairs = pair_nearest(rows_a, rows_b)
    flagged = 0
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "a_frame_index", "a_filename", "a_epoch_ns", "a_num_points",
            "b_frame_index", "b_filename", "b_epoch_ns", "b_num_points",
            "delta_ms", "flagged",
        ])
        for a, b in pairs:
            delta_ms = (b["epoch_ns"] - a["epoch_ns"]) / 1e6
            flag = abs(delta_ms) > max_delta_ms
            if flag:
                flagged += 1
            writer.writerow([
                a["frame_index"], a["filename"], a["epoch_ns"], a["num_points"],
                b["frame_index"], b["filename"], b["epoch_ns"], b["num_points"],
                round(delta_ms, 2), "yes" if flag else "",
            ])
    return len(pairs), flagged


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest_a", required=True, help="lidar_A manifest.csv for the scenario")
    parser.add_argument("--manifest_b", required=True, help="lidar_B manifest.csv for the scenario")
    parser.add_argument("--out", required=True, help="Output combined CSV path")
    parser.add_argument("--max_delta_ms", type=float, default=70.0,
                         help="Flag pairs whose A/B timestamps differ by more than this (ms) — suggests a missing/dropped frame on one side")
    args = parser.parse_args()

    n_pairs, flagged = sync_manifests(args.manifest_a, args.manifest_b, args.out, max_delta_ms=args.max_delta_ms)

    print(f"[sync_scenario_frames] {n_pairs} paires ecrites dans {args.out}")
    if flagged:
        print(f"[sync_scenario_frames] ATTENTION: {flagged} paire(s) avec un ecart > {args.max_delta_ms} ms "
              f"(frame probablement manquante d'un cote)")
    else:
        print(f"[sync_scenario_frames] toutes les paires sont sous {args.max_delta_ms} ms d'ecart")


if __name__ == "__main__":
    main()
