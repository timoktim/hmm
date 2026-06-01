#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "未找到 .venv，请先运行 ./install_macos.command"
  exit 1
fi

mkdir -p data/cache data/db data/models data/logs
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
export LOKY_MAX_CPU_COUNT="${LOKY_MAX_CPU_COUNT:-1}"
export OMP_WAIT_POLICY="${OMP_WAIT_POLICY:-PASSIVE}"
export KMP_BLOCKTIME="${KMP_BLOCKTIME:-0}"
PORT="${PORT:-8501}"
exec .venv/bin/streamlit run app.py --server.port "$PORT" --server.fileWatcherType none
