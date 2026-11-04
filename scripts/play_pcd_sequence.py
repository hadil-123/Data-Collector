#!/usr/bin/env python3
"""Play back a directory of .pcd frames in a single window, one at a time.

Unlike `pcl_viewer file1.pcd file2.pcd ...` (which loads every file into the
same static view), this keeps one window open and swaps the point cloud's
data frame by frame, so you can target a specific per-frame display time.

Also supports saving the playback straight to a video file (via PyVista's
own VTK-based frame writer, not a screen grab), so a scenario can be handed
to someone as an .mp4 instead of a live demo.

The camera is always free to orbit/zoom with the mouse while playing (and
while recording). Press SPACE to pause the sequence — the camera stays
interactive and still gets recorded, so you can rotate/zoom around a
specific frame before resuming. Close the window to stop and finalize the
video.

Usage — live playback only:
    scripts/play_pcd_sequence.py --dir SESSION/derived/lidar_A/pcd/D2 \\
        [--interval_ms 100] [--color_by intensity]

Usage — save to video (window shown, camera interactive, SPACE to pause):
    scripts/play_pcd_sequence.py --dir SESSION/derived/lidar_A/pcd/D2 \\
        --output_video SESSION/derived/lidar_A/pcd/D2.mp4 \\
        --interval_ms 100 --fps 30

Usage — save to video without opening a window (headless, fixed camera,
no interaction possible — use this only when you don't need to rotate/zoom):
    scripts/play_pcd_sequence.py --dir SESSION/derived/lidar_A/pcd/D2 \\
        --output_video SESSION/derived/lidar_A/pcd/D2.mp4 --fps 10 --off_screen
"""
import argparse
import glob
import math
import os
import time

import numpy as np
import pyvista as pv

_DTYPE_MAP = {("F", 4): "<f4", ("U", 2): "<u2", ("U", 4): "<u4", ("I", 4): "<i4"}


def read_pcd_binary(path):
    with open(path, "rb") as f:
        fields = sizes = types = counts = n_points = None
        while True:
            line = f.readline().decode("ascii").strip()
            if line.startswith("FIELDS"):
                fields = line.split()[1:]
            elif line.startswith("SIZE"):
                sizes = [int(x) for x in line.split()[1:]]
            elif line.startswith("TYPE"):
                types = line.split()[1:]
            elif line.startswith("COUNT"):
                counts = [int(x) for x in line.split()[1:]]
            elif line.startswith("POINTS"):
                n_points = int(line.split()[1])
            elif line.startswith("DATA"):
                break
        data = f.read()

    dt_fields = []
    for name, size, typ, count in zip(fields, sizes, types, counts):
        np_type = _DTYPE_MAP[(typ, size)]
        for c in range(count):
            dt_fields.append((name if count == 1 else f"{name}_{c}", np_type))
    return np.frombuffer(data, dtype=np.dtype(dt_fields), count=n_points)


def _swap_frame(plotter, path, color_by, actor, camera_set):
    arr = read_pcd_binary(path)
    # Les deux capteurs sont montes inverses (au plafond, tete en bas) : leur
    # axe Z brut pointe vers le bas reel. On l'inverse pour que "haut" dans
    # le nuage de points corresponde au vrai haut de la piece.
    xyz = np.column_stack([arr["x"], arr["y"], -arr["z"]]).astype(np.float32)

    if actor is not None:
        plotter.remove_actor(actor, render=False)
        actor = None

    if xyz.shape[0] > 0:
        cloud = pv.PolyData(xyz)
        scalars = None
        if color_by != "none" and color_by in arr.dtype.names:
            cloud[color_by] = arr[color_by].astype(np.float32)
            scalars = color_by
        actor = plotter.add_points(
            cloud, scalars=scalars, cmap="turbo", point_size=1.3,
            # Echelle de couleur fixe (pas d'auto-scale par frame) : sinon la
            # meme intensite physique change de couleur d'une frame a l'autre
            # selon qu'un reflet brillant est present ou non dans cette frame
            # precise — et ca ne correspondrait pas non plus a la vue web.
            clim=[0, 120],
            render_points_as_spheres=False, show_scalar_bar=False,
        )
        if not camera_set:
            # Only frame the very first real frame automatically; after that
            # the camera is left alone so mouse orbit/zoom persists across frames.
            plotter.reset_camera()
            camera_set = True
    return actor, camera_set


def estimate_sequence_bounds(files, sample=30, pad_ratio=0.1):
    """Robust bounding box across a sample of frames (1st-99th percentile per
    axis, pooled), so a single stray/noise point in any one frame — including
    the first, which a naive "frame on first frame" approach is vulnerable
    to — can't zoom the camera out to make the subject tiny in the render."""
    step = max(1, len(files) // sample)
    xs, ys, zs = [], [], []
    for path in files[::step]:
        arr = read_pcd_binary(path)
        if arr.shape[0] == 0:
            continue
        xs.append(arr["x"])
        ys.append(arr["y"])
        zs.append(-arr["z"])  # meme inversion que _swap_frame (capteurs montes tete en bas)
    if not xs:
        return None
    xs, ys, zs = np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)
    bounds = []
    for coords in (xs, ys, zs):
        lo, hi = np.percentile(coords, [1, 99])
        pad = (hi - lo) * pad_ratio
        bounds.extend([lo - pad, hi + pad])
    return tuple(bounds)


def eye_level_camera_position(bounds, elevation_deg=22):
    """A human eye-level-ish view (camera pulled back and only slightly
    above the scene) instead of PyVista's default reset_camera(bounds=...),
    which for a flat, room-sized point cloud (small Z extent, large X/Y
    extent) places the camera almost directly overhead — a steep top-down
    angle that's genuinely hard to read as a room and gets misread as
    upside-down/inverted. A modest ~20 deg elevation reads unambiguously."""
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    cx, cy, cz = (xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2
    diag = math.hypot(xmax - xmin, ymax - ymin)
    dist = max(diag * 0.9, 3.0)
    elev = math.radians(elevation_deg)
    horiz = dist * math.cos(elev)
    # Vise depuis le coin oppose (+X/+Y) : l'autre diagonale regardait
    # la scene a l'envers (de dos plutot que de face).
    cam = (
        cx + horiz * 0.7071,
        cy + horiz * 0.7071,
        cz + dist * math.sin(elev),
    )
    return [cam, (cx, cy, cz), (0, 0, 1)]


def run_off_screen(files, args):
    """Fast, non-interactive render straight through — no camera control possible."""
    plotter = pv.Plotter(title="PCD sequence player", off_screen=True)
    plotter.set_background("#0e1117")  # meme fond sombre que la vue 3D interactive de la page web
    if args.output_video:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_video)), exist_ok=True)
        plotter.open_movie(args.output_video, framerate=args.fps)
        print(f"[play_pcd_sequence] recording to {args.output_video} at {args.fps} fps")
    plotter.show(auto_close=False)

    bounds = estimate_sequence_bounds(files)
    camera_position = eye_level_camera_position(bounds) if bounds is not None else None

    actor = None
    for path in files:
        actor, _ = _swap_frame(plotter, path, args.color_by, actor, True)
        if camera_position is not None:
            plotter.camera_position = camera_position
        plotter.render()
        if args.output_video:
            plotter.write_frame()

    plotter.close()
    print(f"[play_pcd_sequence] {len(files)} frames rendered")


def run_interactive(files, args):
    """Window with free camera orbit/zoom at all times. Data frame advances on
    its own clock (--interval_ms); the render/record tick runs on a separate,
    faster clock (--fps) so camera motion stays smooth even between data
    updates. SPACE pauses frame advancement without pausing recording."""
    plotter = pv.Plotter(title="PCD sequence player")
    plotter.set_background("#0e1117")
    if args.output_video:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_video)), exist_ok=True)
        plotter.open_movie(args.output_video, framerate=args.fps)
        print(f"[play_pcd_sequence] recording to {args.output_video} at {args.fps} fps")

    state = {"paused": False}

    def toggle_pause():
        state["paused"] = not state["paused"]
        print("[play_pcd_sequence]", "pause" if state["paused"] else "reprise")

    plotter.add_key_event("space", toggle_pause)
    plotter.add_text(
        "ESPACE: pause/reprise  |  souris: tourner / zoomer  |  fermer la fenetre: arreter",
        position="upper_left", font_size=9, color="white", shadow=True,
    )
    plotter.show(interactive_update=True, auto_close=False)

    actor = None
    camera_set = False
    frame_idx = 0
    data_dt = args.interval_ms / 1000.0
    video_dt = 1.0 / args.fps
    next_data_time = 0.0
    t_start = time.perf_counter()
    announced_done = False

    while not plotter._closed:
        now = time.perf_counter() - t_start
        if not state["paused"] and frame_idx < len(files) and now >= next_data_time:
            actor, camera_set = _swap_frame(plotter, files[frame_idx], args.color_by, actor, camera_set)
            frame_idx += 1
            next_data_time += data_dt
            if frame_idx == len(files) and not announced_done:
                announced_done = True
                print("[play_pcd_sequence] toutes les frames affichees — "
                      "tournez/zoomez librement, fermez la fenetre pour arreter l'enregistrement")

        tick_t0 = time.perf_counter()
        plotter.update()
        if args.output_video:
            plotter.write_frame()
        elapsed = time.perf_counter() - tick_t0
        if elapsed < video_dt:
            time.sleep(video_dt - elapsed)

    plotter.close()
    print(f"[play_pcd_sequence] {frame_idx}/{len(files)} frames affichees")


def frame_epoch_from_path(path):
    """Les fichiers PCD sont nommes '{frame_index:06d}_{epoch_ns}.pcd' —
    extrait l'epoch_ns depuis le nom de fichier."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return int(stem.split("_", 1)[1])


def filter_files_by_epoch(files, start_ns=None, end_ns=None):
    """Ne garde que les fichiers dont l'epoch (dans le nom) tombe dans
    [start_ns, end_ns] — pour isoler une seule prise dans un dossier qui
    contient les frames de plusieurs prises concatenees."""
    if start_ns is None and end_ns is None:
        return files
    lo = start_ns if start_ns is not None else 0
    hi = end_ns if end_ns is not None else float("inf")
    return [f for f in files if lo <= frame_epoch_from_path(f) <= hi]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, help="Directory of .pcd frames to play, in filename order")
    parser.add_argument("--interval_ms", type=float, default=100.0, help="How often the point cloud data frame advances (ms) — 100 = real sensor rate")
    parser.add_argument("--color_by", default="intensity", help="Field to color by, or 'none' for flat color")
    parser.add_argument("--output_video", default=None, help="Also save the playback to this video file (e.g. out.mp4)")
    parser.add_argument("--fps", type=float, default=30.0, help="Video/render frame rate — higher gives smoother camera motion when interactive")
    parser.add_argument("--off_screen", action="store_true", help="Render without opening a window: fast, but no camera interaction (fixed view)")
    parser.add_argument("--start_ns", type=int, default=None,
                         help="Only play frames whose epoch_ns (embedded in the filename) is >= this — for a single take within a multi-take scenario folder")
    parser.add_argument("--end_ns", type=int, default=None,
                         help="Only play frames whose epoch_ns (embedded in the filename) is <= this")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, "*.pcd")))
    if not files:
        raise SystemExit(f"No .pcd files found in {args.dir}")

    if args.start_ns is not None or args.end_ns is not None:
        files = filter_files_by_epoch(files, args.start_ns, args.end_ns)
        if not files:
            raise SystemExit(f"No .pcd files in {args.dir} within [{args.start_ns}, {args.end_ns}]")

    print(f"[play_pcd_sequence] {len(files)} frames, data advances every {args.interval_ms:.0f} ms")

    if args.off_screen:
        run_off_screen(files, args)
    else:
        run_interactive(files, args)


if __name__ == "__main__":
    main()
