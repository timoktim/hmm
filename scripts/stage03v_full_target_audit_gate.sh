#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

choose_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
  elif [[ -x .venv/bin/python ]]; then
    printf '%s\n' ".venv/bin/python"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
  else
    echo "STAGE03V_FULL_TARGET_AUDIT_GATE=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

choose_pytest() {
  if [[ -n "${PYTEST_BIN:-}" ]]; then
    printf '%s\n' "$PYTEST_BIN"
  elif [[ -x .venv/bin/pytest ]]; then
    printf '%s\n' ".venv/bin/pytest"
  elif command -v pytest >/dev/null 2>&1; then
    printf '%s\n' "pytest"
  else
    echo "STAGE03V_FULL_TARGET_AUDIT_GATE=blocked"
    echo "No pytest executable found. Expected PYTEST_BIN, .venv/bin/pytest, or pytest."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
PYTEST_CMD="$(choose_pytest)"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"
TARGET_SUPPORT="${STAGE03V_FULL_TARGET_AUDIT_TARGET_SUPPORT:-reports/stage03v/risk_event_target_support.json}"
TARGET_UNIVERSE="${STAGE03V_FULL_TARGET_AUDIT_TARGET_UNIVERSE:-configs/stage03v_sw_l2_target_universe_v1.yaml}"
TARGET_CONTROLS="${STAGE03V_FULL_TARGET_AUDIT_TARGET_CONTROLS:-reports/stage03v/target_controls_report.json}"
FOLD_PLAN="${STAGE03V_FULL_TARGET_AUDIT_FOLD_PLAN:-reports/stage03v/purge_embargo_fold_plan.json}"
OUTPUT_MD="${STAGE03V_FULL_TARGET_AUDIT_OUTPUT:-reports/stage03v/full_target_streaming_audit_report.md}"
SUMMARY_JSON="${STAGE03V_FULL_TARGET_AUDIT_SUMMARY_JSON:-reports/stage03v/full_target_streaming_audit_report.json}"
CHUNK_SUMMARY="${STAGE03V_FULL_TARGET_AUDIT_CHUNK_SUMMARY:-reports/stage03v/full_target_streaming_audit_chunk_summary.csv}"
ERROR_SAMPLE="${STAGE03V_FULL_TARGET_AUDIT_ERROR_SAMPLE:-reports/stage03v/full_target_streaming_audit_error_sample.csv}"
CHUNK_SIZE="${STAGE03V_FULL_TARGET_AUDIT_CHUNK_SIZE:-250000}"

echo "STAGE03V_FULL_TARGET_AUDIT_DB=${DB_PATH}"

"$PYTHON_CMD" -m compileall -q src tests
"$PYTEST_CMD" -q tests/test_stage03v_full_target_audit.py
"$PYTHON_CMD" -m src.evaluation.stage03v_full_target_audit \
  --db "$DB_PATH" \
  --target-support "$TARGET_SUPPORT" \
  --target-universe "$TARGET_UNIVERSE" \
  --target-controls "$TARGET_CONTROLS" \
  --fold-plan "$FOLD_PLAN" \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --chunk-summary "$CHUNK_SUMMARY" \
  --error-sample "$ERROR_SAMPLE" \
  --chunk-size "$CHUNK_SIZE" \
  --no-fetch
"$PYTHON_CMD" -m json.tool "$SUMMARY_JSON" >/dev/null

gate_status="fail"
report_db_path="$DB_PATH"
rows_checked="0"
expected_rows="0"
if [[ -f "$SUMMARY_JSON" ]]; then
  gate_status="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('status', 'fail'))" "$SUMMARY_JSON")"
  report_db_path="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('source_db_path', sys.argv[2]))" "$SUMMARY_JSON" "$DB_PATH")"
  rows_checked="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('full_target_rows_checked', 0))" "$SUMMARY_JSON")"
  expected_rows="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('expected_target_row_count', 0))" "$SUMMARY_JSON")"
fi

echo "STAGE03V_FULL_TARGET_AUDIT_GATE=${gate_status} db=${report_db_path} rows_checked=${rows_checked} expected_rows=${expected_rows} report=${OUTPUT_MD} summary_json=${SUMMARY_JSON} no_fetch=yes"
