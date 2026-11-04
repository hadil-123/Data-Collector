"""Logique pure utilisee par la page Visualisation, extraite dans ce module
pour pouvoir etre testee (pytest) sans importer streamlit ni executer une
page entiere — webui/pages/1_Visualisation.py ne fait qu'importer d'ici et
assembler l'UI."""
import base64
import csv
import json
import os
import re
import subprocess
from datetime import datetime, timezone

import numpy as np

from lidar_collector.pcd import read_pcd_binary, invert_ceiling_mount_z


def load_sync_pairs(session_base, scenario_id):
    sync_path = os.path.join(session_base, 'derived', f'sync_{scenario_id}.csv')
    if not os.path.isfile(sync_path):
        return []
    with open(sync_path, newline='') as f:
        return list(csv.DictReader(f))


def frame_arrays(path, max_points):
    arr = read_pcd_binary(path)
    n = arr.shape[0]
    if n == 0:
        z = np.zeros(0, dtype="<f4")
        return z, z, z, z
    idx = np.arange(n)
    if n > max_points:
        idx = np.random.default_rng(0).choice(n, max_points, replace=False)
    return (arr["x"][idx].astype("<f4"), arr["y"][idx].astype("<f4"),
            invert_ceiling_mount_z(arr["z"][idx]).astype("<f4"), arr["intensity"][idx].astype("<f4"))


def b64f32(chunks):
    """Concatene des arrays float32 et les encode en base64 : ~4x plus
    compact et bien plus rapide a decoder cote navigateur qu'un gros
    tableau JSON de nombres (observe : un payload JSON equivalent prenait
    plus de 2 min a charger, ceci est quasi instantane)."""
    flat = np.concatenate(chunks) if chunks else np.zeros(0, dtype="<f4")
    return base64.b64encode(flat.tobytes()).decode("ascii")


def dual_pcd_viewer_html(rows, dir_a, dir_b, plotlyjs, max_points=50000, max_frames=30, height=560):
    """Composant HTML/JS autonome : Plotly.js (le texte JS complet, passe en
    parametre pour eviter de dependre de plotly.offline ici) est charge UNE
    fois dans l'iframe, et les boutons precedent/suivant appellent
    Plotly.react() sur le MEME graphique pour changer juste les points
    affiches. Comme le graphique n'est jamais detruit/recree (contrairement
    a st.plotly_chart qui repart de zero a chaque rerun Streamlit), la
    camera (rotation/zoom) reste exactement ou l'utilisateur l'a laissee,
    frame apres frame."""
    step = max(1, len(rows) // max_frames)
    sampled = rows[::step]

    xa_c, ya_c, za_c, ca_c = [], [], [], []
    xb_c, yb_c, zb_c, cb_c = [], [], [], []
    offsets_a, offsets_b = [0], [0]
    labels = []
    for row in sampled:
        x, y, z, c = frame_arrays(os.path.join(dir_a, row['a_filename']), max_points)
        xa_c.append(x); ya_c.append(y); za_c.append(z); ca_c.append(c)
        offsets_a.append(offsets_a[-1] + len(x))
        x, y, z, c = frame_arrays(os.path.join(dir_b, row['b_filename']), max_points)
        xb_c.append(x); yb_c.append(y); zb_c.append(z); cb_c.append(c)
        offsets_b.append(offsets_b[-1] + len(x))
        labels.append(f"Frame A #{row['a_frame_index']} · Frame B #{row['b_frame_index']} · "
                       f"écart: {row.get('delta_ms', '0')} ms")

    data = {
        "offsetsA": offsets_a, "offsetsB": offsets_b,
        "xa": b64f32(xa_c), "ya": b64f32(ya_c), "za": b64f32(za_c), "ca": b64f32(ca_c),
        "xb": b64f32(xb_c), "yb": b64f32(yb_c), "zb": b64f32(zb_c), "cb": b64f32(cb_c),
        "labels": labels, "n": len(sampled),
    }

    bg = "#0e1117"
    grid_color = "#2a2e39"

    return f"""
    <div style="font-family: 'Source Sans Pro', sans-serif; background:{bg}; padding:8px; border-radius:6px; position:relative;">
      <div id="loadingMsg" style="position:absolute; inset:8px; display:flex; align-items:center;
           justify-content:center; color:#aaa; font-size:15px; z-index:5; background:{bg};">
        ⏳ Chargement du nuage de points ({len(sampled)} frames)...
      </div>
      <div style="display:flex; gap:12px;">
        <div id="plotA" style="flex:1; height:{height}px;"></div>
        <div id="plotB" style="flex:1; height:{height}px;"></div>
      </div>
      <div style="text-align:center; margin-top:10px;">
        <button id="prevBtn" style="font-size:16px; padding:4px 14px; cursor:pointer;">⬅️</button>
        <span id="frameLabel" style="margin:0 14px; color:#ccc;"></span>
        <button id="nextBtn" style="font-size:16px; padding:4px 14px; cursor:pointer;">➡️</button>
      </div>
    </div>
    <script>{plotlyjs}</script>
    <script>
      const DATA = {json.dumps(data)};
      let idx = 0;

      function b64ToF32(b64) {{
        const bin = atob(b64);
        const buf = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
        return new Float32Array(buf.buffer);
      }}
      const XA = b64ToF32(DATA.xa), YA = b64ToF32(DATA.ya), ZA = b64ToF32(DATA.za), CA = b64ToF32(DATA.ca);
      const XB = b64ToF32(DATA.xb), YB = b64ToF32(DATA.yb), ZB = b64ToF32(DATA.zb), CB = b64ToF32(DATA.cb);

      // Cercles de distance centres sur le capteur (0,0,0), comme dans
      // VeloView, pour donner un repere d'echelle au nuage de points.
      function distanceRings(radii, nPts) {{
        const traces = [];
        for (const r of radii) {{
          const xs = [], ys = [], zs = [];
          for (let k = 0; k <= nPts; k++) {{
            const a = (k / nPts) * 2 * Math.PI;
            xs.push(r * Math.cos(a)); ys.push(r * Math.sin(a)); zs.push(0);
          }}
          traces.push({{
            type: 'scatter3d', mode: 'lines', x: xs, y: ys, z: zs,
            line: {{color: '{grid_color}', width: 2}}, hoverinfo: 'skip', showlegend: false,
          }});
          traces.push({{
            type: 'scatter3d', mode: 'text', x: [r], y: [0], z: [0],
            text: [r + 'm'], textfont: {{color: '#666', size: 10}},
            hoverinfo: 'skip', showlegend: false,
          }});
        }}
        return traces;
      }}
      const GRID = distanceRings([5, 10, 15, 20], 72);

      const layout = {{
        margin: {{l:0,r:0,t:0,b:0}},
        paper_bgcolor: '{bg}', plot_bgcolor: '{bg}',
        showlegend: false,
        scene: {{
          aspectmode: 'data', bgcolor: '{bg}',
          xaxis: {{visible:false}}, yaxis: {{visible:false}}, zaxis: {{visible:false}},
          // Angle de depart "on entre dans la piece" (~22deg d'elevation),
          // au lieu de l'angle par defaut de Plotly (1.25/1.25/1.25) qui
          // regarde presque du dessus — il fallait tourner a la main avant.
          camera: {{eye: {{x: 1.3, y: 1.3, z: 0.75}}}},
        }},
        uirevision: 'constant',
      }};
      function trace(xs, ys, zs, cs, offsets, i) {{
        const a = offsets[i], b = offsets[i + 1];
        return [{{
          type: 'scatter3d', mode: 'markers',
          x: xs.subarray(a, b), y: ys.subarray(a, b), z: zs.subarray(a, b),
          marker: {{size: 1.1, color: cs.subarray(a, b), colorscale: 'Turbo', cmin: 0, cmax: 120}}
        }}, ...GRID];
      }}
      function render(i) {{
        const pa = Plotly.react('plotA', trace(XA, YA, ZA, CA, DATA.offsetsA, i), layout);
        const pb = Plotly.react('plotB', trace(XB, YB, ZB, CB, DATA.offsetsB, i), layout);
        document.getElementById('frameLabel').innerText = DATA.labels[i];
        document.getElementById('prevBtn').disabled = (i <= 0);
        document.getElementById('nextBtn').disabled = (i >= DATA.n - 1);
        return Promise.all([pa, pb]);
      }}
      render(0).then(() => {{
        const msg = document.getElementById('loadingMsg');
        if (msg) msg.style.display = 'none';
      }});
      document.getElementById('prevBtn').onclick = () => {{ if (idx > 0) {{ idx--; render(idx); }} }};
      document.getElementById('nextBtn').onclick = () => {{ if (idx < DATA.n - 1) {{ idx++; render(idx); }} }};
    </script>
    """


# ---------------------------------------------------------------------------
# Vidéos participant (caméras téléphone) : chaque session peut avoir un
# dossier Videos/MP4 avec des clips iPhone nommés par iOS, ex:
# "20261031_184748000_iOS.mp4" — ce nom encode l'heure de depart en UTC
# (confirme : nom de fichier - 4h = heure reelle affichee sur l'iPhone, soit
# l'heure locale Montreal/Sherbrooke EDT = UTC-4). On s'en sert pour recaler
# chaque clip sur la meme horloge que epoch_ns du journal de session, sans
# dependre du nom du fichier au-dela de son prefixe horodate.
IOS_VIDEO_RE = re.compile(r'^(\d{8})_(\d{6})\d{3}_iOS', re.IGNORECASE)


def parse_ios_video_epoch(filename):
    m = IOS_VIDEO_RE.match(filename)
    if not m:
        return None
    date_str, time_str = m.groups()
    dt = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def video_duration_seconds(path, ffmpeg_bin):
    try:
        result = subprocess.run([ffmpeg_bin, "-i", path], capture_output=True, text=True, timeout=20)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if not m:
            return None
        h, mnt, s = m.groups()
        return int(h) * 3600 + int(mnt) * 60 + float(s)
    except Exception:
        return None


def participant_videos_dir(session_base):
    d = os.path.join(session_base, 'Videos', 'MP4')
    return d if os.path.isdir(d) else None


def list_participant_videos(videos_dir, ffmpeg_bin):
    """[{path, name, start(epoch s), end(epoch s)}], triees par heure de depart."""
    out = []
    for fname in sorted(os.listdir(videos_dir)):
        if not fname.lower().endswith('.mp4'):
            continue
        start = parse_ios_video_epoch(fname)
        if start is None:
            continue
        path = os.path.join(videos_dir, fname)
        dur = video_duration_seconds(path, ffmpeg_bin)
        if dur is None:
            continue
        out.append({"path": path, "name": fname, "start": start, "end": start + dur})
    out.sort(key=lambda f: f["start"])
    return out


def find_covering_clips(videos, start_epoch_s, end_epoch_s, margin=2.0):
    """Fichiers dont la fenetre couvre entierement [start,end] (+ marge),
    avec l'offset (s) et la duree (s) a extraire dans chacun."""
    matches = []
    for f in videos:
        if f["start"] <= start_epoch_s and end_epoch_s <= f["end"]:
            offset = max(0.0, start_epoch_s - f["start"] - margin)
            real_start = f["start"] + offset
            duration = (end_epoch_s - start_epoch_s) + (start_epoch_s - real_start) + margin
            matches.append({"file": f, "offset": offset, "duration": duration})
    return matches


def extract_clip(src_path, offset_s, duration_s, out_path, ffmpeg_bin):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    subprocess.run(
        [ffmpeg_bin, "-y", "-ss", str(offset_s), "-i", src_path, "-t", str(duration_s),
         "-c", "copy", out_path],
        capture_output=True, text=True, timeout=60,
    )


def find_sessions(base_dir):
    """Find session dirs (S<id>_P<id>_<timestamp>) anywhere under base_dir,
    not just one level down — "Data Root Dir" is a free-text field (see
    streamlit_app.py), so a session can land at base_dir/S.../ as well as
    base_dir/data/some_label/S.../ depending on what was typed.

    Walks with os.walk (not a recursive glob) so matched session dirs and
    hidden dirs (.venv, .git, ...) get pruned instead of being scanned into —
    a session's derived/ can hold thousands of small .pcd frame files, which
    a recursive glob would have to stat on every call just to discard."""
    import fnmatch
    sessions = []
    for root, dirs, _files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        matched = [d for d in dirs if fnmatch.fnmatch(d, 'S*_P*_*')]
        for d in matched:
            path = os.path.join(root, d)
            if os.path.isdir(os.path.join(path, 'derived', 'lidar_A', 'pcd')):
                sessions.append(path)
        dirs[:] = [d for d in dirs if d not in matched]
    sessions.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return sessions


def find_scenario_ids(session_base):
    pcd_a_dir = os.path.join(session_base, 'derived', 'lidar_A', 'pcd')
    if not os.path.isdir(pcd_a_dir):
        return []
    return sorted(d for d in os.listdir(pcd_a_dir) if os.path.isdir(os.path.join(pcd_a_dir, d)))


def video_path(session_base, sensor, scenario_id, take_idx):
    return os.path.join(session_base, 'derived', sensor, 'pcd', f"{scenario_id}_prise{take_idx + 1}.mp4")


def pcd_dir(session_base, sensor, scenario_id):
    return os.path.join(session_base, 'derived', sensor, 'pcd', scenario_id)
