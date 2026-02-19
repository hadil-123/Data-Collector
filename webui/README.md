# Lidar Session Manager - Streamlit Web UI

## Installation

Depuis la racine du projet:

```bash
python3 -m venv webui/.venv
source webui/.venv/bin/activate
pip install --upgrade pip
pip install -r webui/requirements.txt
```

Si `conda` n'est pas installe (`conda: command not found`), utilisez cette sequence:

```bash
cd ~/Bureau/lidar-dataset-collector-main
python3 -m venv webui/.venv
source webui/.venv/bin/activate
pip install --upgrade pip
pip install -r webui/requirements.txt
cd webui
streamlit run streamlit_app.py
```

Pour quitter l'environnement virtuel:

```bash
deactivate
```

## Compilation du recorder C++ (obligatoire)

Depuis la racine du projet:

```bash
cmake -S recorder -B recorder/build
cmake --build recorder/build -j
```

Binaire attendu:

```bash
./recorder/build/recorder
```

En cas d'erreur de cache CMake (ancien chemin):

```bash
rm -rf recorder/build
cmake -S recorder -B recorder/build
cmake --build recorder/build -j
```

## Run

```bash
cd webui
streamlit run streamlit_app.py
```

L'UI s'ouvrira sur http://localhost:8501

## Features

- ✅ Démarrer/arrêter une session
- ✅ Gestion des scénarios (start/stop)
- ✅ Logs automatiques (session_log.csv)
- ✅ Configuration des capteurs
- ✅ Enregistrement brut séparé par capteur (`raw/pcap/*.pcap` et `raw/bag/*.bag`)
- ✅ Enregistrement RosBag auto (`ros2 bag` si dispo, sinon `rosbag` Noetic)
- ✅ Téléchargement des logs
- ✅ Interface moderne et responsive

## RosBag (ROS1/ROS2)

- Active l'option `Enregistrer RosBag auto (ROS1/ROS2)` dans la sidebar.
- Renseigne `Topic capteur A` et `Topic capteur B` (si capteur B activé).
- Optionnel: active `Auto-lancer commandes ROS` pour lancer `roscore` + drivers directement depuis l'UI.
- L'application détecte automatiquement:
  - `ros2` -> lance `ros2 bag record`
  - sinon `rosbag` -> lance `rosbag record` (Noetic)
- Pré-vol avant démarrage:
  - ROS2: vérifie `ros2 topic list`
  - ROS1: vérifie `rostopic list` (donc `roscore` doit être actif)
  - vérifie que les topics saisis existent réellement
- Les sorties sont écrites dans `raw/rosbag/` avec 2 fichiers séparés:
  - capteur A: `lidar_A_ros1.bag` (ROS1) ou dossier `lidar_A_ros2` (ROS2)
  - capteur B: `lidar_B_ros1.bag` (ROS1) ou dossier `lidar_B_ros2` (ROS2)
- Important: il faut lancer Streamlit dans un shell où ROS est sourcé (`source /opt/ros/<distro>/setup.bash`).

### Exemple 2 capteurs (ROS1 Noetic)

- `Topic capteur A`: `/lidar_a/velodyne_points`
- `Topic capteur B`: `/lidar_b/velodyne_points`
- `Commande ROS core`: `roscore`
- `Commande driver capteur A`:
  `roslaunch velodyne_pointcloud VLP-32C_points.launch __ns:=lidar_a device_ip:=192.168.1.202`
- `Commande driver capteur B`:
  `roslaunch velodyne_pointcloud VLP-32C_points.launch __ns:=lidar_b device_ip:=192.168.1.201`

Notes:
- Selon la version du package, l'argument IP peut s'appeler `device_ip` ou `rpm`/autres paramètres peuvent être requis.
- Vérifie toujours les topics publiés avec `rostopic list` et adapte les champs de l'UI.
