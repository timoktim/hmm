#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"
PYTEST_BIN="${PYTEST_BIN:-pytest}"
OUTPUT_DIR="${GPT_INFO_EXCHANGE_OUTPUT_DIR:-reports/gpt_exchange/latest}"
ARCHIVE_DIR="${GPT_INFO_EXCHANGE_ARCHIVE_DIR:-reports/gpt_exchange/archive}"
POLICY="${GPT_INFO_EXCHANGE_POLICY:-configs/gpt_info_exchange_policy_v1.yaml}"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_gpt_info_exchange.py
"$PYTHON_BIN" -m src.integrations.gpt_info_exchange \
  --policy "$POLICY" \
  --output-dir "$OUTPUT_DIR" \
  --archive-dir "$ARCHIVE_DIR" \
  --synthetic \
  --no-push
"$PYTHON_BIN" -m json.tool "$OUTPUT_DIR/signal_bundle.json" >/dev/null
"$PYTHON_BIN" -m json.tool "$OUTPUT_DIR/provenance.json" >/dev/null
"$PYTHON_BIN" -m json.tool "$OUTPUT_DIR/exchange_manifest.json" >/dev/null
"$PYTHON_BIN" -m json.tool reports/gpt_exchange/sample_manifest.json >/dev/null
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check

"$PYTHON_BIN" - "$OUTPUT_DIR/exchange_manifest.json" "$OUTPUT_DIR" <<'PY'
from __future__ import annotations

import json
import sys

manifest_path, output_dir = sys.argv[1], sys.argv[2]
manifest = json.loads(open(manifest_path, encoding="utf-8").read())
status = "pass" if manifest.get("not_trading_output") == "yes" else "fail"
print(
    "GPT_INFO_EXCHANGE_GATE="
    f"{status} output_dir={output_dir} "
    f"exchange_repo_status={manifest['exchange_repo_status']} "
    f"snapshot_rows={manifest['snapshot_rows']} "
    f"watchlists={manifest['watchlists_generated']} "
    f"not_trading_output=yes push={manifest['push_executed']}"
)
PY
