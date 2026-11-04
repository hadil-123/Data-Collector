#!/usr/bin/env python3
"""Decode a Velodyne pcap capture into a sequence of per-frame PCD files.

Each output .pcd holds one full sensor rotation (one frame), named with its
frame index and epoch_ns capture timestamp, so the temporal sequence can be
replayed in order. If a scenario log CSV (scenario_start/scenario_end rows
with epoch_ns, as produced by the webui) is given, each frame is additionally
tagged with the scenario_id whose [start, end] interval contains it.

Usage:
    scripts/pcap_to_pcd.py --pcap SESSION/raw/pcap/lidar_A.pcap \\
        --out_dir SESSION/derived/lidar_A/pcd \\
        [--model VLP32C] \\
        [--scenario_csv SESSION/logs/lidar_A_log.csv] \\
        [--split_by_scenario]
"""
import argparse
import csv
import os

import dpkt
import numpy as np
import velodyne_decoder as vd

# Column order of the plain float array returned by vd.read_pcap(as_pcl_structs=False),
# per velodyne_decoder.PointField.
FIELDS = ("x", "y", "z", "intensity", "time", "column", "ring", "return_type")


def write_pcd_binary(path, points):
    n = points.shape[0]
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        f"FIELDS {' '.join(FIELDS)}\n"
        f"SIZE {' '.join(['4'] * len(FIELDS))}\n"
        f"TYPE {' '.join(['F'] * len(FIELDS))}\n"
        f"COUNT {' '.join(['1'] * len(FIELDS))}\n"
        f"WIDTH {n}\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {n}\n"
        "DATA binary\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(np.ascontiguousarray(points, dtype="<f4").tobytes())


def load_scenario_intervals(scenario_csv):
    """Pair scenario_start/scenario_end rows into (start_ns, end_ns, scenario_id) intervals."""
    open_starts = {}
    intervals = []
    with open(scenario_csv, newline="") as f:
        for row in csv.DictReader(f):
            event = row.get("event", "")
            scenario_id = row.get("scenario_id", "")
            epoch_ns = row.get("epoch_ns", "")
            if not epoch_ns:
                continue
            epoch_ns = int(epoch_ns)
            if event == "scenario_start":
                open_starts[scenario_id] = epoch_ns
            elif event == "scenario_end" and scenario_id in open_starts:
                intervals.append((open_starts.pop(scenario_id), epoch_ns, scenario_id))
    intervals.sort()
    return intervals


def scenario_for_ts(intervals, epoch_ns):
    for start_ns, end_ns, scenario_id in intervals:
        if start_ns <= epoch_ns <= end_ns:
            return scenario_id
    return ""


def extract_scenario_frames(pcap_path, out_dir, scenario_id, start_ns, end_ns, model="VLP32C"):
    """Decode only the frames within [start_ns, end_ns] into out_dir/<scenario_id>/.

    Appends to that scenario's manifest.csv, so repeated takes of the same
    scenario_id in one session accumulate rather than overwrite. Returns the
    number of frames written.
    """
    scen_dir = os.path.join(out_dir, scenario_id)
    os.makedirs(scen_dir, exist_ok=True)
    manifest_path = os.path.join(scen_dir, "manifest.csv")
    write_header = not os.path.exists(manifest_path)
    frame_index = len([f for f in os.listdir(scen_dir) if f.endswith(".pcd")])
    start_index = frame_index

    config = vd.Config(model=vd.Model[model])
    time_range = (start_ns / 1e9, end_ns / 1e9)

    with open(manifest_path, "a", newline="") as manifest_f:
        writer = csv.writer(manifest_f)
        if write_header:
            writer.writerow(["frame_index", "epoch_ns", "filename", "num_points", "scenario_id"])
        for timestamp, points in vd.read_pcap(pcap_path, config, time_range=time_range):
            epoch_ns = round(timestamp.host * 1e9)
            filename = f"{frame_index:06d}_{epoch_ns}.pcd"
            write_pcd_binary(os.path.join(scen_dir, filename), points)
            writer.writerow([frame_index, epoch_ns, filename, points.shape[0], scenario_id])
            frame_index += 1

    return frame_index - start_index


def extract_scenario_pcap(pcap_path, out_path, start_ns, end_ns):
    """Copy the raw packets within [start_ns, end_ns] into a new, standalone .pcap file.

    Packet-level copy (no LiDAR decoding), so this is fast and preserves the
    exact original bytes — the result opens in VeloView/Wireshark/etc. just
    like the full-session pcap, but scoped to a single scenario.
    """
    start_s, end_s = start_ns / 1e9, end_ns / 1e9
    n = 0
    with open(pcap_path, "rb") as fin, open(out_path, "wb") as fout:
        reader = dpkt.pcap.Reader(fin)
        writer = dpkt.pcap.Writer(fout, linktype=reader.datalink())
        it = iter(reader)
        while True:
            try:
                ts, buf = next(it)
            except StopIteration:
                break
            except dpkt.dpkt.NeedData:
                # Truncated trailing record — e.g. the recorder was killed
                # mid-write. Treat it as end of available data instead of
                # failing the whole extraction (the record itself is unusable
                # either way).
                break
            if ts > end_s:
                break
            if ts >= start_s:
                writer.writepkt(buf, ts=ts)
                n += 1
    return n


def extract_scenario(pcap_path, out_dir, scenario_id, start_ns, end_ns, model="VLP32C"):
    """Extract both the PCD frames and a standalone .pcap for one scenario.

    Mirrors the CLI's --single_scenario_id behavior as a plain function, so
    callers (e.g. an orchestrator that also runs the sync step afterward)
    don't have to shell out. Returns (n_frames, n_packets, pcap_out_path).
    """
    os.makedirs(out_dir, exist_ok=True)
    n_frames = extract_scenario_frames(pcap_path, out_dir, scenario_id, start_ns, end_ns, model=model)

    pcap_out_dir = os.path.join(os.path.dirname(os.path.normpath(out_dir)), "pcap")
    os.makedirs(pcap_out_dir, exist_ok=True)
    pcap_out_path = os.path.join(pcap_out_dir, f"{scenario_id}.pcap")
    if os.path.exists(pcap_out_path):
        # Don't silently overwrite an earlier take of the same scenario_id.
        take = 2
        while os.path.exists(os.path.join(pcap_out_dir, f"{scenario_id}_{take}.pcap")):
            take += 1
        pcap_out_path = os.path.join(pcap_out_dir, f"{scenario_id}_{take}.pcap")
    n_pkts = extract_scenario_pcap(pcap_path, pcap_out_path, start_ns, end_ns)
    return n_frames, n_pkts, pcap_out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pcap", required=True, help="Input .pcap file written by the recorder")
    parser.add_argument("--out_dir", required=True, help="Output directory for per-frame .pcd files")
    parser.add_argument("--model", default="VLP32C", choices=[m.name for m in vd.Model], help="Sensor model (default: VLP32C)")
    parser.add_argument("--scenario_csv", default=None, help="Optional scenario log CSV to tag frames by activity")
    parser.add_argument("--split_by_scenario", action="store_true", help="Also copy frames into out_dir/<scenario_id>/ subfolders")
    parser.add_argument("--single_scenario_id", default=None,
                         help="Extract only this one scenario's frames (requires --start_ns/--end_ns) instead of the whole pcap")
    parser.add_argument("--start_ns", type=int, default=None, help="Scenario start, epoch nanoseconds (with --single_scenario_id)")
    parser.add_argument("--end_ns", type=int, default=None, help="Scenario end, epoch nanoseconds (with --single_scenario_id)")
    args = parser.parse_args()

    if args.single_scenario_id:
        if args.start_ns is None or args.end_ns is None:
            raise SystemExit("--single_scenario_id requires --start_ns and --end_ns")
        n_frames, n_pkts, pcap_out_path = extract_scenario(
            args.pcap, args.out_dir, args.single_scenario_id, args.start_ns, args.end_ns, model=args.model)
        print(f"[pcap_to_pcd] wrote {n_frames} frames for scenario {args.single_scenario_id} to "
              f"{os.path.join(args.out_dir, args.single_scenario_id)}")
        print(f"[pcap_to_pcd] wrote {n_pkts} packets for scenario {args.single_scenario_id} to {pcap_out_path}")
        return

    os.makedirs(args.out_dir, exist_ok=True)

    intervals = load_scenario_intervals(args.scenario_csv) if args.scenario_csv else []

    config = vd.Config(model=vd.Model[args.model])
    manifest_path = os.path.join(args.out_dir, "manifest.csv")
    with open(manifest_path, "w", newline="") as manifest_f:
        writer = csv.writer(manifest_f)
        writer.writerow(["frame_index", "epoch_ns", "filename", "num_points", "scenario_id"])

        frame_index = 0
        for timestamp, points in vd.read_pcap(args.pcap, config):
            # `.host` is the recording machine's wall-clock receive time (epoch seconds),
            # comparable to the epoch_ns timestamps in the webui's scenario log CSV.
            epoch_ns = round(timestamp.host * 1e9)
            scenario_id = scenario_for_ts(intervals, epoch_ns) if intervals else ""
            filename = f"{frame_index:06d}_{epoch_ns}.pcd"
            out_path = os.path.join(args.out_dir, filename)
            write_pcd_binary(out_path, points)

            if args.split_by_scenario and scenario_id:
                scen_dir = os.path.join(args.out_dir, scenario_id)
                os.makedirs(scen_dir, exist_ok=True)
                write_pcd_binary(os.path.join(scen_dir, filename), points)

            writer.writerow([frame_index, epoch_ns, filename, points.shape[0], scenario_id])
            frame_index += 1

    print(f"[pcap_to_pcd] wrote {frame_index} frames to {args.out_dir}")
    print(f"[pcap_to_pcd] manifest: {manifest_path}")


if __name__ == "__main__":
    main()
