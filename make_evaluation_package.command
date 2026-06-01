#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE_TAG="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT_DIR/a_share_hmm_analyzer_vnext_evaluation_${DATE_TAG}.zip"

cd "$ROOT_DIR"
zip -qr "$OUT" . \
  -x "./.venv/*" \
  -x "./.venv*" \
  -x "./.venv*/*" \
  -x "./.pytest_cache/*" \
  -x ".pytest_cache/*" \
  -x "__pycache__/" \
  -x "*/__pycache__/" \
  -x "*/__pycache__/*" \
  -x "*.pyc" \
  -x "data/db/" \
  -x "data/db/*" \
  -x "data/cache/" \
  -x "data/cache/*" \
  -x "data/models/" \
  -x "data/models/*" \
  -x "data/logs/" \
  -x "data/logs/*" \
  -x "./data/db/*" \
  -x "./data/cache/*" \
  -x "./data/models/*" \
  -x "./data/logs/*" \
  -x "*.zip" \
  -x ".DS_Store" \
  -x "*/.DS_Store"

echo "已生成评估包：$OUT"
