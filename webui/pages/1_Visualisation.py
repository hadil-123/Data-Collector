import streamlit as st
import streamlit.components.v1 as components
import subprocess
import os
import sys
import yaml
import plotly.offline as pyo
import imageio_ffmpeg

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # webui/
PROJECT_ROOT = os.path.dirname(BASE_DIR)
SCENARIOS_PATH = os.path.join(PROJECT_ROOT, 'configs', 'scenarios.yaml')
PLAYER_SCRIPT = os.path.join(PROJECT_ROOT, 'lidar_collector', 'playback', 'play_pcd_sequence.py')
VELOVIEW_SCRIPT = os.path.join(PROJECT_ROOT, 'scripts', 'open_scenario_veloview.py')
VIDEO_FPS = 10  # correspond au taux natif du capteur (10 Hz) pour une duree video realiste
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

sys.path.insert(0, BASE_DIR)
from lidar_collector.capture import pcap_to_pcd
import viz_helpers as vh  # noqa: E402 - needs sys.path set up first

st.set_page_config(page_title="Visualisation des scenarios", page_icon="🎥", layout="wide")
st.title("🎥 Visualisation des scénarios")
st.caption("Choisissez une session et un scénario pour revoir les deux capteurs côte à côte.")

try:
    with open(SCENARIOS_PATH) as f:
        SCENARIOS_CFG = yaml.safe_load(f)
except OSError:
    SCENARIOS_CFG = {'scenarios': []}
SCENARIO_META = {s['id']: s for s in SCENARIOS_CFG.get('scenarios', [])}

sessions = vh.find_sessions(BASE_DIR)
if not sessions:
    st.warning("Aucune session avec des scénarios extraits n'a été trouvée sous webui/.")
    st.stop()

session_display = [os.path.relpath(s, BASE_DIR) for s in sessions]
sel_session = st.selectbox("Session :", range(len(sessions)), format_func=lambda i: session_display[i])
session_base = sessions[sel_session]

scenario_ids = vh.find_scenario_ids(session_base)
if not scenario_ids:
    st.warning("Aucun scénario extrait pour cette session (le pipeline de traitement n'a peut-être pas encore tourné).")
    st.stop()

scenario_display = [f"[{sid}] {SCENARIO_META.get(sid, {}).get('label', sid)}" for sid in scenario_ids]
sel_scenario = st.selectbox("Scénario :", range(len(scenario_ids)), format_func=lambda i: scenario_display[i])
scenario_id = scenario_ids[sel_scenario]

meta = SCENARIO_META.get(scenario_id, {})
if meta:
    c1, c2, c3 = st.columns(3)
    c1.metric("Catégorie", meta.get('category', 'N/A'))
    c2.metric("Zone", meta.get('zone', 'N/A'))
    c3.metric("Difficulté", meta.get('difficulty', 'N/A'))

# Un scenario_id peut avoir ete repete plusieurs fois dans la session (prises
# multiples) — PCD/sync/video melangent toutes les prises dans un seul
# fichier, mais les .pcap et les videos participant sont bien separes par
# prise. On calcule l'intervalle horaire de la prise choisie une seule fois
# ici, et on s'en sert pour filtrer les trois sections ci-dessous de la
# meme facon (coherence : avant seule la video participant le faisait).
log_path_a = os.path.join(session_base, 'logs', 'lidar_A_log.csv')
all_intervals = pcap_to_pcd.load_scenario_intervals(log_path_a) if os.path.isfile(log_path_a) else []
takes = [iv for iv in all_intervals if iv[2] == scenario_id]

if len(takes) > 1:
    take_labels = [f"Prise {i + 1} ({(e - s) / 1e9:.0f}s)" for i, (s, e, _) in enumerate(takes)]
    take_idx = st.selectbox("Prise :", range(len(takes)), format_func=lambda i: take_labels[i])
else:
    take_idx = 0

take_start_ns, take_end_ns = (takes[take_idx][0], takes[take_idx][1]) if takes else (None, None)

st.divider()

video_a = vh.video_path(session_base, 'lidar_A', scenario_id, take_idx)
video_b = vh.video_path(session_base, 'lidar_B', scenario_id, take_idx)
dir_a = vh.pcd_dir(session_base, 'lidar_A', scenario_id)
dir_b = vh.pcd_dir(session_base, 'lidar_B', scenario_id)

missing_videos = [p for p in (video_a, video_b) if not os.path.exists(p)]

if missing_videos:
    st.info("Les vidéos de cette prise n'ont pas encore été générées (rendu à partir des frames PCD, ~1-2 min).")
    if st.button("🎬 Générer les vidéos (Capteur A + B)", use_container_width=True):
        progress = st.empty()
        for label, pdir, vpath in (("A", dir_a, video_a), ("B", dir_b, video_b)):
            if os.path.exists(vpath):
                continue
            progress.info(f"Génération de la vidéo Capteur {label}...")
            cmd = [sys.executable, PLAYER_SCRIPT, "--dir", pdir, "--output_video", vpath,
                   "--off_screen", "--fps", str(VIDEO_FPS)]
            if take_start_ns is not None:
                cmd += ["--start_ns", str(take_start_ns), "--end_ns", str(take_end_ns)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                st.error(f"Échec de la génération pour Capteur {label} :\n{result.stderr[-2000:]}")
                st.stop()
        progress.empty()
        st.rerun()
else:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Capteur A")
        st.video(video_a)
    with col_b:
        st.subheader("Capteur B")
        st.video(video_b)

    if st.button("🔄 Régénérer les vidéos"):
        for vpath in (video_a, video_b):
            try:
                os.remove(vpath)
            except OSError:
                pass
        st.rerun()

st.divider()
st.subheader("🧭 Vue 3D interactive (rotation / zoom à la souris, dans la page)")

pairs = vh.load_sync_pairs(session_base, scenario_id)
if take_start_ns is not None:
    # Le fichier de sync couvre toutes les prises concatenees : ne garder que
    # les paires de la prise selectionnee, comme pour la video participant.
    pairs = [r for r in pairs if take_start_ns <= int(r['a_epoch_ns']) <= take_end_ns]
if not pairs:
    st.info("Pas de fichier de synchronisation pour ce scénario — impossible d'afficher la vue 3D appariée.")
else:
    viewer_key = f"viz_viewer_html_{session_base}_{scenario_id}_prise{take_idx + 1}"
    if viewer_key not in st.session_state:
        with st.spinner("Préparation de la vue 3D..."):
            st.session_state[viewer_key] = vh.dual_pcd_viewer_html(pairs, dir_a, dir_b, pyo.get_plotlyjs())
    components.html(st.session_state[viewer_key], height=630, scrolling=False)
    st.caption("⬅️ / ➡️ avancent les deux capteurs ensemble, frame par frame. "
               "La rotation/zoom que vous appliquez reste la même d'une frame à l'autre.")

st.divider()
st.subheader("🎥 Vidéo du participant (extrait synchronisé)")

videos_dir = vh.participant_videos_dir(session_base)
if not videos_dir:
    st.info("Pas de dossier Videos/MP4 pour cette session.")
elif not takes:
    st.info("Pas d'intervalle horaire retrouvé pour ce scénario dans le journal de session.")
else:
    start_s, end_s = take_start_ns / 1e9, take_end_ns / 1e9

    videos_key = f"participant_videos_{videos_dir}"
    if videos_key not in st.session_state:
        with st.spinner("Lecture des métadonnées vidéo..."):
            st.session_state[videos_key] = vh.list_participant_videos(videos_dir, FFMPEG_BIN)
    videos = st.session_state[videos_key]

    clips = vh.find_covering_clips(videos, start_s, end_s)
    if not clips:
        st.warning("Aucun extrait vidéo (Videos/MP4) ne couvre cette prise — "
                   "le clip correspondant n'a peut-être pas été converti/déposé.")
    else:
        clip_dir = os.path.join(session_base, 'derived', 'participant_video')
        out_paths = [
            os.path.join(clip_dir, f"{scenario_id}_prise{take_idx + 1}_cam{i + 1}.mp4")
            for i in range(len(clips))
        ]
        missing = [p for p in out_paths if not os.path.exists(p)]
        if missing:
            st.info(f"{len(clips)} extrait(s) vidéo trouvé(s) pour cette prise, pas encore extraits.")
            if st.button("✂️ Extraire les vidéos de cette prise", use_container_width=True):
                with st.spinner("Extraction des extraits vidéo..."):
                    for clip, out_path in zip(clips, out_paths):
                        vh.extract_clip(clip["file"]["path"], clip["offset"], clip["duration"], out_path, FFMPEG_BIN)
                st.rerun()
        else:
            cols = st.columns(len(out_paths))
            for i, (col, clip, out_path) in enumerate(zip(cols, clips, out_paths)):
                with col:
                    st.caption(f"Caméra {i + 1} — {clip['file']['name']}")
                    st.video(out_path)
            if st.button("🔄 Ré-extraire"):
                for p in out_paths:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                st.rerun()

st.divider()
st.caption("Alternative : ouvrir le pcap complet de cette prise dans VeloView (lecture temps réel, les deux capteurs) :")
if st.button("🛰️ Ouvrir en direct dans VeloView (fenêtres séparées)"):
    subprocess.Popen([sys.executable, VELOVIEW_SCRIPT, "--session", session_base,
                       "--scenario_id", scenario_id, "--take", str(take_idx + 1)])
    st.success("VeloView lancé pour les deux capteurs (deux fenêtres vont s'ouvrir).")
