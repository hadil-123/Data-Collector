# lidar-dataset-collector

Collecte de donnees LiDAR (PCAP + RosBag) avec une interface Streamlit.

## Prerequis

```bash
sudo apt update
sudo apt install -y build-essential cmake python3 python3-venv python3-pip
```

## Structure utile

- Recorder C++: `recorder/`
- UI Streamlit: `webui/`
- Config capteurs: `configs/sensors.yaml`
- Launch ROS2 dual lidar: `ros2/dual_velodyne_vlp32c.launch.py`
- Scripts start/stop stack complete: `scripts/start_ros_ui.sh`, `scripts/stop_ros_ui.sh`

## 1) Compiler le recorder C++

Depuis la racine du projet:

```bash
cmake -S recorder -B recorder/build
cmake --build recorder/build -j
```

Binaire genere:

```bash
./recorder/build/recorder
```

Si erreur de cache CMake:

```bash
rm -rf recorder/build
cmake -S recorder -B recorder/build
cmake --build recorder/build -j
```

Option (mode capture raw sans sudo, recommande):

```bash
sudo setcap cap_net_raw,cap_net_admin+eip recorder/build/recorder
getcap recorder/build/recorder
```

## 2) Environnement Python (UI)

```bash
python3 -m venv webui/.venv
source webui/.venv/bin/activate
pip install --upgrade pip
pip install -r webui/requirements.txt
```

Quitter le venv:

```bash
deactivate
```

## 3) ROS2 (Ubuntu 24.04 -> Jazzy)

Verifier:

```bash
ls /opt/ros
source /opt/ros/jazzy/setup.bash
echo $ROS_DISTRO
```

Installer si besoin:

```bash
sudo apt update
sudo apt install -y ros-jazzy-ros-base ros-jazzy-velodyne ros-jazzy-velodyne-driver ros-jazzy-velodyne-pointcloud
```

## 4) Config capteurs

Edite `configs/sensors.yaml`:

```yaml
sensor_a:
  ip: 192.168.1.202
sensor_b:
  ip: 192.168.1.201
port: 2368
interface: enx3c18a0c1f237
```

## 5) Demarrage simplifie (1 commande)

Depuis la racine du projet:

```bash
./scripts/start_ros_ui.sh
```

Ce script lance:

1. ROS2 dual lidar (`ros2/dual_velodyne_vlp32c.launch.py`)
2. RViz2 (si display GUI disponible)
3. Streamlit (`http://localhost:8501`)

Arret de tout:

```bash
./scripts/stop_ros_ui.sh
```

Logs runtime:

- `.run/logs/ros2_dual.log`
- `.run/logs/streamlit.log`
- `.run/logs/rviz.log`

## 6) Enregistrer PCAP + RosBag depuis l'UI

Dans l'UI (`http://localhost:8501`):

1. Activer capteur B
2. Cocher `Enregistrer RosBag auto (ROS1/ROS2)`
3. Topics:

```text
/lidar_a/velodyne_points
/lidar_b/velodyne_points
```

4. Cliquer `Start Session`, puis `Stop Session`

Sorties session:

- PCAP: `.../raw/pcap/lidar_A.pcap`, `.../raw/pcap/lidar_B.pcap`
- RosBag2: `.../raw/rosbag/lidar_A_ros2/`, `.../raw/rosbag/lidar_B_ros2/`
- Logs: `.../logs/recorder.log`, `.../logs/rosbag_record_a.log`, `.../logs/rosbag_record_b.log`

## 7) Lire un RosBag et l'afficher avec RViz

### 7.1 Infos RosBag

```bash
source /opt/ros/jazzy/setup.bash
ros2 bag info /chemin/vers/lidar_A_ros2
```

### 7.2 Rejouer RosBag

```bash
source /opt/ros/jazzy/setup.bash
ros2 bag play /chemin/vers/lidar_A_ros2
```

### 7.3 Visualiser dans RViz

Terminal 1:

```bash
source /opt/ros/jazzy/setup.bash
rviz2
```

Dans RViz:

1. `Fixed Frame`: `lidar_a` (ou frame du topic)
2. `Add` -> `PointCloud2`
3. Topic: `/lidar_a/velodyne_points`

Terminal 2:

```bash
source /opt/ros/jazzy/setup.bash
ros2 bag play /chemin/vers/lidar_A_ros2
```

## 8) Verifications rapides

Verifier topics ROS2:

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic list | grep -E "lidar_a|lidar_b|velodyne_points"
```

Verifier taille des sorties:

```bash
ls -lh data/<dossier_session>/raw/pcap
ls -lh data/<dossier_session>/raw/rosbag/lidar_A_ros2
ls -lh data/<dossier_session>/raw/rosbag/lidar_B_ros2
```

## 9) Troubleshooting

- Option RosBag grisee dans l'UI:
  - lancer Streamlit dans un shell ou ROS2 est source (`source /opt/ros/jazzy/setup.bash`)
  - verifier `which ros2` avant `streamlit run ...`
  - verifier qu'aucune session n'est active (`Stop Session`), puis recharger l'UI
- PCAP vide (24 octets):
  - verifier firewall/ufw UDP 2368
  - verifier interface reseau dans `configs/sensors.yaml`
- `ros2 topic list` sans topics lidar:
  - verifier que le launch dual tourne (`.run/logs/ros2_dual.log`)

### Erreur `socket(AF_PACKET): Operation not permitted`

Le binaire recorder n'a pas les capacites raw apres un rebuild.

```bash
cd ~/Bureau/lidar-dataset-collector-main
sudo setcap cap_net_raw,cap_net_admin+eip recorder/build/recorder
getcap recorder/build/recorder
```

### Erreur `bind(AF_INET): Address already in use`

Le port UDP `2368` est deja occupe (souvent par `velodyne_driver`).

```bash
sudo ss -lunp | grep :2368
pkill -f velodyne_driver
```

Puis relancer la session.
