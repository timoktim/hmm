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
    echo "STAGE03V_RISK_TARGET_GATE=blocked"
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
    echo "STAGE03V_RISK_TARGET_GATE=blocked"
    echo "No pytest executable found. Expected PYTEST_BIN, .venv/bin/pytest, or pytest."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
PYTEST_CMD="$(choose_pytest)"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"
FEASIBILITY="${STAGE03V_RISK_TARGET_FEASIBILITY:-reports/stage03v/sample_feasibility_report.json}"
OUTPUT_MD="${STAGE03V_RISK_TARGET_OUTPUT:-reports/stage03v/risk_event_target_support.md}"
SUMMARY_JSON="${STAGE03V_RISK_TARGET_SUMMARY_JSON:-reports/stage03v/risk_event_target_support.json}"
SAMPLE_CSV="${STAGE03V_RISK_TARGET_SAMPLE_CSV:-reports/stage03v/risk_event_target_dataset_sample.csv}"

echo "STAGE03V_RISK_TARGET_DB=${DB_PATH}"

"$PYTHON_CMD" -m compileall -q src tests
"$PYTEST_CMD" -q tests/test_stage03v_path_targets.py tests/test_stage03v_risk_target_dataset.py
"$PYTHON_CMD" -m src.evaluation.stage03v_risk_target_dataset \
  --db "$DB_PATH" \
  --feasibility "$FEASIBILITY" \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --sample-csv "$SAMPLE_CSV" \
  --no-fetch

gate_status="fail"
report_db_path="$DB_PATH"
if [[ -f "$SUMMARY_JSON" ]]; then
  gate_status="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('status', 'fail'))" "$SUMMARY_JSON")"
  report_db_path="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('source_db_path', sys.argv[2]))" "$SUMMARY_JSON" "$DB_PATH")"
fi

echo "STAGE03V_RISK_TARGET_GATE=${gate_status} db=${report_db_path} report=${OUTPUT_MD} summary_json=${SUMMARY_JSON} no_fetch=yes"
