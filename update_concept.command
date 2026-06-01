#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "未找到 .venv，请先运行 ./install_macos.command"
  exit 1
fi

START_DATE="${1:-20200101}"
END_DATE="${2:-today}"
LIMIT="${3:-10}"
WORKERS="${WORKERS:-1}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-10}"

exec .venv/bin/python -m src.data_pipeline.updater --board-type concept --start "$START_DATE" --end "$END_DATE" --limit "$LIMIT" --skip-constituents --incremental --lookback-days "$LOOKBACK_DAYS" --workers "$WORKERS"
