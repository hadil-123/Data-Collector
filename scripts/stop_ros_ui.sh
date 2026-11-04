#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/.run/pids.env"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No running stack found ($PID_FILE missing)."
  exit 0
fi

# shellcheck disable=SC1090
source "$PID_FILE"

kill_tree() {
  local pid="$1"
  local child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

kill_pid() {
  local name="$1"
  local pid="$2"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill_tree "$pid"
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "Stopped $name (pid=$pid)"
  fi
}

kill_pid "streamlit" "${STREAMLIT_PID:-}"
kill_pid "rviz2" "${RVIZ_PID:-}"
kill_pid "ros2 launch" "${ROS_PID:-}"

rm -f "$PID_FILE"
echo "Stack stopped."
