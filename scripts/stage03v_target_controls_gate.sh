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
    echo "STAGE03V_TARGET_CONTROLS_GATE=blocked"
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
    echo "STAGE03V_TARGET_CONTROLS_GATE=blocked"
    echo "No pytest executable found. Expected PYTEST_BIN, .venv/bin/pytest, or pytest."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
PYTEST_CMD="$(choose_pytest)"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"
TARGET_SUPPORT="${STAGE03V_TARGET_CONTROLS_TARGET_SUPPORT:-reports/stage03v/risk_event_target_support.json}"
TARGET_UNIVERSE="${STAGE03V_TARGET_CONTROLS_TARGET_UNIVERSE:-configs/stage03v_sw_l2_target_universe_v1.yaml}"
FEASIBILITY="${STAGE03V_TARGET_CONTROLS_FEASIBILITY:-reports/stage03v/sample_feasibility_report.json}"
POLICY="${STAGE03V_TARGET_CONTROLS_POLICY:-configs/stage03v_purge_embargo_policy_v1.yaml}"
OUTPUT_MD="${STAGE03V_TARGET_CONTROLS_OUTPUT:-reports/stage03v/target_controls_report.md}"
SUMMARY_JSON="${STAGE03V_TARGET_CONTROLS_SUMMARY_JSON:-reports/stage03v/target_controls_report.json}"
FOLD_PLAN="${STAGE03V_TARGET_CONTROLS_FOLD_PLAN:-reports/stage03v/purge_embargo_fold_plan.json}"
AUDIT_SAMPLE="${STAGE03V_TARGET_CONTROLS_AUDIT_SAMPLE:-reports/stage03v/target_controls_audit_sample.csv}"

echo "STAGE03V_TARGET_CONTROLS_DB=${DB_PATH}"

"$PYTHON_CMD" -m compileall -q src tests
"$PYTEST_CMD" -q tests/test_stage03v_target_controls.py tests/test_stage03v_purge_embargo.py
"$PYTHON_CMD" -m src.evaluation.stage03v_target_controls \
  --db "$DB_PATH" \
  --target-support "$TARGET_SUPPORT" \
  --target-universe "$TARGET_UNIVERSE" \
  --feasibility "$FEASIBILITY" \
  --policy "$POLICY" \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --fold-plan "$FOLD_PLAN" \
  --audit-sample "$AUDIT_SAMPLE" \
  --no-fetch
"$PYTHON_CMD" -m json.tool "$SUMMARY_JSON" >/dev/null
"$PYTHON_CMD" -m json.tool "$FOLD_PLAN" >/dev/null
"$PYTHON_CMD" -m json.tool "$POLICY" >/dev/null

gate_status="fail"
report_db_path="$DB_PATH"
if [[ -f "$SUMMARY_JSON" ]]; then
  gate_status="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('status', 'fail'))" "$SUMMARY_JSON")"
  report_db_path="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('source_db_path', sys.argv[2]))" "$SUMMARY_JSON" "$DB_PATH")"
fi

echo "STAGE03V_TARGET_CONTROLS_GATE=${gate_status} db=${report_db_path} report=${OUTPUT_MD} summary_json=${SUMMARY_JSON} fold_plan=${FOLD_PLAN} no_fetch=yes"
