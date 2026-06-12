#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"
PYTEST_BIN="${PYTEST_BIN:-pytest}"
OUTPUT="${HSMM_PERFORMANCE_MATRIX_OUTPUT:-reports/hsmm_diagnostics/hsmm_performance_matrix_report.md}"
SUMMARY_JSON="${HSMM_PERFORMANCE_MATRIX_JSON:-reports/hsmm_diagnostics/hsmm_performance_matrix_report.json}"
SUMMARY_CSV="${HSMM_PERFORMANCE_MATRIX_CSV:-reports/hsmm_diagnostics/hsmm_performance_matrix_summary.csv}"
PRESET_CONFIG="${HSMM_PERFORMANCE_PRESET_CONFIG:-configs/hsmm_performance_presets_v1.yaml}"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_hsmm_performance_matrix.py
bash scripts/check_hsmm_numba_engine.sh
"$PYTHON_BIN" -m src.evaluation.hsmm_performance_matrix \
  --output "$OUTPUT" \
  --summary-json "$SUMMARY_JSON" \
  --summary-csv "$SUMMARY_CSV" \
  --preset-config "$PRESET_CONFIG" \
  --mode synthetic \
  --no-db-write
"$PYTHON_BIN" -m json.tool "$SUMMARY_JSON" >/dev/null
"$PYTHON_BIN" -m json.tool "$PRESET_CONFIG" >/dev/null
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check

"$PYTHON_BIN" - "$SUMMARY_JSON" "$OUTPUT" <<'PY'
from __future__ import annotations

import json
import sys

summary_json, output = sys.argv[1], sys.argv[2]
payload = json.loads(open(summary_json, encoding="utf-8").read())
summary = payload["summary"]
print(
    "HSMM_PERF0_1_2_GATE="
    f"{payload['status']} profiles={summary['profile_count']} "
    f"bottleneck={summary['bottleneck_classification']} "
    f"numba_status={summary['numba_status']} fallback_rows={summary['fallback_rows']} "
    f"report={output} summary_json={summary_json} no_db_write=yes"
)
PY
