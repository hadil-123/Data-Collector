#!/usr/bin/env bash
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"
PID_FILE="$RUN_DIR/pids.env"

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  echo "A running stack was detected ($PID_FILE)."
  echo "Run: $ROOT_DIR/scripts/stop_ros_ui.sh"
  exit 1
fi

if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo "ROS2 Jazzy not found at /opt/ros/jazzy/setup.bash"
  exit 1
fi

# ROS setup scripts may reference optional unset vars; keep nounset disabled here.
source /opt/ros/jazzy/setup.bash

if [[ -f "$ROOT_DIR/webui/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/webui/.venv/bin/activate"
else
  echo "Python venv missing at webui/.venv"
  exit 1
fi

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 command not found after sourcing Jazzy"
  exit 1
fi
if ! command -v streamlit >/dev/null 2>&1; then
  echo "streamlit command not found in webui/.venv"
  exit 1
fi

ROS_LAUNCH="$ROOT_DIR/ros2/dual_velodyne_vlp32c.launch.py"
if [[ ! -f "$ROS_LAUNCH" ]]; then
  echo "Custom launch file not found: $ROS_LAUNCH"
  exit 1
fi

# Start dual lidar ROS2 stack
nohup ros2 launch "$ROS_LAUNCH" > "$LOG_DIR/ros2_dual.log" 2>&1 &
ROS_PID=$!
sleep 2
if ! kill -0 "$ROS_PID" 2>/dev/null; then
  echo "ROS2 launch exited early. Check: $LOG_DIR/ros2_dual.log"
  exit 1
fi

# Start RViz if GUI display is available
RVIZ_PID=""
if [[ -n "${DISPLAY:-}" ]]; then
  nohup rviz2 > "$LOG_DIR/rviz.log" 2>&1 &
  RVIZ_PID=$!
fi

# Start Streamlit UI
nohup streamlit run "$ROOT_DIR/webui/streamlit_app.py" > "$LOG_DIR/streamlit.log" 2>&1 &
STREAMLIT_PID=$!
sleep 2
if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
  echo "Streamlit exited early. Check: $LOG_DIR/streamlit.log"
  kill "$ROS_PID" 2>/dev/null || true
  exit 1
fi

cat > "$PID_FILE" <<PIDS
ROS_PID=$ROS_PID
RVIZ_PID=$RVIZ_PID
STREAMLIT_PID=$STREAMLIT_PID
PIDS

echo "Stack started."
echo "  ROS2 log:      $LOG_DIR/ros2_dual.log"
echo "  Streamlit log: $LOG_DIR/streamlit.log"
if [[ -n "$RVIZ_PID" ]]; then
  echo "  RViz log:      $LOG_DIR/rviz.log"
fi
echo "UI: http://localhost:8501"
echo "Stop all: $ROOT_DIR/scripts/stop_ros_ui.sh"
