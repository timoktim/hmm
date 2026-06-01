#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT_DIR/a_share_hmm_analyzer_macos_clean_source.zip"

cd "$ROOT_DIR"
rm -f "$OUT"
zip -qr "$OUT" . \
  -x "./.venv*" \
  -x "./.venv*/*" \
  -x ".venv*" \
  -x ".venv*/*" \
  -x "./.pytest_cache/*" \
  -x ".pytest_cache/*" \
  -x "__pycache__/" \
  -x "*/__pycache__/" \
  -x "*/__pycache__/*" \
  -x "*.pyc" \
  -x ".DS_Store" \
  -x "*/.DS_Store" \
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
  -x "*.zip"

echo "已生成干净源码包：$OUT"
