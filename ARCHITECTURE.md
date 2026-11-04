# Architecture

Ce document complète le [README.md](README.md) (installation / démarrage) :
il décrit **comment le projet est organisé**, **ce que fait chaque fichier**,
et **l'historique du refactor** qui a produit cette organisation.

## Vue d'ensemble

Le projet a trois couches, qui correspondent aux trois dossiers racine
principaux :

| Couche | Dossier | Rôle |
|---|---|---|
| Capture bas niveau | `recorder/` (C++17) | Écoute les paquets UDP des capteurs et les écrit sur disque le plus vite et le plus fidèlement possible — aucune interprétation du contenu LiDAR. |
| Logique partagée | `lidar_collector/` (Python, package installable) | Tout ce qui lit/transforme ces fichiers après coup : décodage PCD, synchronisation des deux capteurs, rejeu/visualisation, et les utilitaires de session réutilisés par l'UI. |
| Interface | `webui/` (Streamlit) | Pilote une session de collecte (boutons Start/Stop) et affiche les résultats. Ne contient (depuis le refactor) que de la logique d'affichage/état — la logique métier vit dans `lidar_collector/`. |

`scripts/` contient les petits outils lancés en ligne de commande ou en
sous-processus par l'UI (pas des modules importés). `configs/` contient tout
ce qui est spécifique à l'installation (IP des capteurs, chemins d'outils
externes, catalogue de scénarios) pour que rien de ça ne soit codé en dur
dans le code Python/C++.

## Flux de données d'une session réelle

```
Capteurs VLP-32C (UDP:2368)
        │
        ▼
┌───────────────────┐   écrit            ┌─────────────────────────┐
│  recorder/recorder │ ───────────────▶ │ SESSION/raw/pcap/*.pcap  │
│  (binaire C++)     │                   │ SESSION/raw/bag/*.bag   │  (optionnel)
└───────────────────┘                    └─────────────────────────┘
        ▲ lancé par                                  │
        │ subprocess.Popen                           │ lu par, au clic "Stop Scenario"
┌───────────────────┐                                ▼
│ webui/             │   lance en bg    ┌───────────────────────────────┐
│ streamlit_app.py   │ ───────────────▶ │ lidar_collector/capture/       │
│ (Start/Stop Session,│                 │   process_scenario.py          │
│  Start/Stop Scenario)│                │   → pcap_to_pcd.py (décodage)  │
└───────────────────┘                   │   → sync_scenario_frames.py    │
        │                               └───────────────────────────────┘
        │ logs CSV (session_log, lidar_A_log, lidar_B_log)                │
        ▼                                                                 ▼
SESSION/logs/*.csv                                      SESSION/derived/lidar_A/pcd/<id>/*.pcd
SESSION/meta/session_meta.yaml                           SESSION/derived/lidar_B/pcd/<id>/*.pcd
                                                          SESSION/derived/sync_<id>.csv
                                                                             │
                                                                             ▼
                                               webui/pages/1_Visualisation.py
                                               → lidar_collector/playback/play_pcd_sequence.py
                                               → scripts/open_scenario_veloview.py (optionnel)
```

Résumé en mots :

1. **Start Session** (`streamlit_app.py`) lance `recorder` en sous-processus
   (process group détaché) ; `recorder` écrit directement les `.pcap`
   (et `.bag` si activé) pendant toute la session — c'est le seul programme
   qui touche au réseau.
2. **Start/Stop Scenario** écrit juste des lignes dans les logs CSV
   (horodatage de début/fin). Au **Stop Scenario**, l'UI relit ces logs et
   lance `lidar_collector/capture/process_scenario.py` en arrière-plan : il
   extrait les frames PCD + un `.pcap` scoped à ce scénario pour chaque
   capteur (`pcap_to_pcd.py`), puis synchronise les deux capteurs par
   timestamp le plus proche (`sync_scenario_frames.py`).
3. La page **Visualisation** (`webui/pages/1_Visualisation.py`) relit ces
   fichiers `derived/` pour rejouer une séquence (`play_pcd_sequence.py`),
   l'exporter en vidéo, ou l'ouvrir dans VeloView
   (`open_scenario_veloview.py`).

## Fichier par fichier

### `recorder/` — capture C++

| Fichier | Responsabilité |
|---|---|
| `main.cpp` | Point d'entrée : ouvre le(s) socket(s) `AF_PACKET` en lecture brute sur l'interface réseau, horodate chaque paquet au noyau (`SO_TIMESTAMPNS`), route vers `PcapWriter`/`BagWriter`. |
| `args.h` / `args.cpp` | Parsing des arguments CLI (`--out_dir`, `--ip_a`, `--port`, `--enable_bag`, ...) en une struct `Args`. |
| `packet_parse.h` / `packet_parse.cpp` | Décode une trame Ethernet brute jusqu'à son payload UDP (IPv4/UDP uniquement), filtre par port de destination attendu. |
| `pcap_writer.h` / `pcap_writer.cpp` | Écrit le format `.pcap` standard (compatible Wireshark/VeloView/dpkt). |
| `bag_writer.h` / `bag_writer.cpp` | Écrit le format `.bag` interne du recorder (alternative/complément au RosBag ROS). |
| `CMakeLists.txt` | Build du binaire `recorder` ; `-DBUILD_TESTS=ON` ajoute la cible `recorder_tests` (Catch2), désactivée par défaut pour que le build normal n'ait pas besoin de Catch2 installé. |
| `tests/test_*.cpp` | Suite Catch2 (24 cas, 88 assertions) : `test_args`, `test_packet_parse`, `test_pcap_writer`, `test_bag_writer`. |

### `lidar_collector/` — package Python partagé (`pip install -e .`)

#### `lidar_collector/pcd/` — format de fichier PCD et correction capteur

| Fichier | Responsabilité |
|---|---|
| `io.py` | Lecture/écriture du format PCD binaire minimal utilisé pour une frame LiDAR. Point d'entrée unique de ce format — avant le refactor, cette logique était dupliquée 3 fois. |
| `geometry.py` | `invert_ceiling_mount_z()` : les deux VLP-32C sont montés au plafond tête en bas, donc leur axe Z brut pointe vers le bas réel — cette fonction corrige ça pour tout affichage/calcul géométrique. |

#### `lidar_collector/capture/` — pipeline post-enregistrement

| Fichier | Responsabilité |
|---|---|
| `pcap_to_pcd.py` | Décode un `.pcap` Velodyne en séquence de frames `.pcd` (une par rotation complète) + `manifest.csv`. Sait aussi découper un `.pcap` sur un intervalle de temps (extraction par scénario). |
| `sync_scenario_frames.py` | Apparie les frames `lidar_A`/`lidar_B` d'un même scénario par timestamp le plus proche, écrit une table combinée, signale les écarts anormaux (frame probablement manquante d'un côté). |
| `process_scenario.py` | Orchestrateur appelé par le bouton **Stop Scenario** : extraction A, puis B, puis synchro, dans un seul process pour garantir l'ordre. |

#### `lidar_collector/playback/` — rejeu / export

| Fichier | Responsabilité |
|---|---|
| `play_pcd_sequence.py` | Rejoue un dossier de frames `.pcd` dans une fenêtre PyVista (caméra libre), avec export vidéo optionnel. |
| `play_scenario_dual.py` | Lance deux `play_pcd_sequence.py` (capteur A et B) côte à côte pour comparer. |

#### `lidar_collector/session/` — logique de session (extraite de `streamlit_app.py`)

| Fichier | Responsabilité |
|---|---|
| `paths.py` | Résolution du binaire recorder, formatage octets/temps, espace disque, comptage de paquets dans un `.pcap` en cours d'écriture, lecture des derniers logs. |
| `recorder_control.py` | Détection du mode RosBag (ROS1/ROS2), construction de la commande `rosbag record`, pré-vol ROS (vérifie que les topics existent), lancement/arrêt de process en arrière-plan. |
| `scenario_log.py` | Lecture/écriture de `session_meta.yaml`, détection d'un scénario en cours (non fermé), comptage des prises complétées, initialisation des fichiers CSV de log. |

Ces trois modules sont **purs** (aucune dépendance à `st.session_state`) et
couverts par 45 tests de caractérisation (`tests/test_session_*.py`) —
c'était le code le moins testé du projet avant le refactor.

### `webui/` — interface Streamlit

| Fichier | Responsabilité |
|---|---|
| `streamlit_app.py` | Page principale : configuration capteurs (sidebar), Start/Stop Session (lance `recorder`, gère RosBag), Start/Stop Scenario (écrit les logs, lance `process_scenario.py`), monitoring live, logs. Orchestration uniquement — la logique métier est importée de `lidar_collector.*`. |
| `pages/1_Visualisation.py` | Page secondaire : choisit une session/scénario, rejoue les deux capteurs côte à côte, export vidéo, ouverture VeloView. |
| `viz_helpers.py` | Logique pure derrière la page Visualisation (chargement des paires synchronisées, génération du composant Plotly.js, gestion des vidéos participant) — séparée pour être testable sans Streamlit. |

### `scripts/` — outils ligne de commande / sous-processus

| Fichier | Responsabilité |
|---|---|
| `open_scenario_veloview.py` | Ouvre les `.pcap` A et B d'un scénario dans deux fenêtres VeloView déjà calibrées. Lit les chemins VeloView dans `configs/tools.yaml`. |
| `start_ros_ui.sh` | Démarrage en une commande : stack ROS2 dual-capteur + RViz (si display) + Streamlit. Écrit les PID dans `.run/pids.env`. |
| `stop_ros_ui.sh` | Arrête tout ce que `start_ros_ui.sh` a lancé (via `.run/pids.env`). |

### `configs/` — tout ce qui est spécifique à l'installation

| Fichier | Contenu |
|---|---|
| `sensors.yaml` | IP des capteurs A/B, port UDP, interface réseau. |
| `scenarios.yaml` | Catalogue des scénarios proposés dans l'UI (id, label, catégorie, difficulté). |
| `ui_config.yaml` | `session_data_root` — dossier racine où les sessions sont écrites par défaut. |
| `tools.yaml` | Chemin du binaire VeloView et du fichier de calibration (spécifique à la machine). |

### `ros2/`, `tests/`, racine

| Fichier | Responsabilité |
|---|---|
| `ros2/dual_velodyne_vlp32c.launch.py` | Lance les deux stacks ROS2 Velodyne (driver + pointcloud) avec des namespaces/topics séparés pour A et B. |
| `tests/*.py` | Suite pytest (91 tests) : décodage PCD, sync, playback, VeloView, `viz_helpers`, et les 3 modules de `lidar_collector/session/`. `conftest.py` met en place le `sys.path` pour les imports historiques (`scripts/` encore sur le path pour `open_scenario_veloview`). |
| `pyproject.toml` | Déclare `lidar_collector` comme package installable (`pip install -e .`), ce qui permet `from lidar_collector.xxx import yyy` depuis n'importe où sans bricoler `sys.path`. |
| `README.md` | Installation, démarrage, troubleshooting (ce document-ci ne répète pas ce contenu). |

## Historique du refactor

Travail fait sur la branche `refactor/architecture-cible` (créée depuis
`version-0`, un checkpoint stable poussé avant toute modification), en
suivant la contrainte : ne jamais casser une fonctionnalité existante, tester
avant/après chaque étape, préférer déplacer le code plutôt que le réécrire.

1. **Centralisation PCD + géométrie** — l'I/O du format PCD et l'inversion
   Z du montage plafond étaient dupliquées dans 3 fichiers ; regroupées dans
   `lidar_collector/pcd/`.
2. **Déplacement capture/playback** — `pcap_to_pcd.py`,
   `sync_scenario_frames.py`, `process_scenario.py` → `lidar_collector/capture/` ;
   `play_pcd_sequence.py`, `play_scenario_dual.py` → `lidar_collector/playback/`.
   Mise à jour des deux points d'appel réels (`streamlit_app.py`,
   `1_Visualisation.py`), vérifié en ré-exécutant le pipeline sur une vraie
   collecte.
3. **Extraction de `lidar_collector/session/`** — 19 fonctions pures
   sorties de `streamlit_app.py` (~1150 lignes, 0 test au départ), avec 45
   tests de caractérisation écrits avant le déplacement.
4. **Nettoyage** — suppression du code mort `DEMO_MODE`/`DummyProc`,
   dédoublonnage de `configs/ui_config.yaml` (bloc répété 3 fois), ajout
   d'un avertissement visible sur le champ "Data Root Dir" (cause du bug qui
   a créé plusieurs dossiers de sessions réelles directement sous `webui/`
   au lieu de `data/`).
5. **`configs/tools.yaml`** — sortie des chemins VeloView codés en dur
   dans `open_scenario_veloview.py`.

Chaque étape : suite pytest complète verte, `streamlit run` vérifié sans
exception serveur, et pour les étapes touchant Start/Stop Session ou
Start/Stop Scenario, une vraie collecte testée avec les capteurs avant de
passer à la suite.
