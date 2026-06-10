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
    echo "STAGE03V_SAMPLE_FEASIBILITY_GATE=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
DB_PATH="${STAGE03V_V7_DB:-${STAGE03V_SAMPLE_FEASIBILITY_DB:-data/db/a_share_hmm_tushare_v7.duckdb}}"
OUTPUT_MD="${STAGE03V_SAMPLE_FEASIBILITY_OUTPUT:-reports/stage03v/sample_feasibility_report.md}"
SUMMARY_JSON="${STAGE03V_SAMPLE_FEASIBILITY_SUMMARY_JSON:-reports/stage03v/sample_feasibility_report.json}"

set +e
"$PYTHON_CMD" -m src.evaluation.stage03v_sample_feasibility \
  --db "$DB_PATH" \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --no-fetch
status=$?
set -e

gate_status="fail"
report_db_path="$DB_PATH"
if [[ -f "$SUMMARY_JSON" ]]; then
  gate_status="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('status', 'fail'))" "$SUMMARY_JSON")"
  report_db_path="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('db_path', sys.argv[2]))" "$SUMMARY_JSON" "$DB_PATH")"
fi

echo "STAGE03V_SAMPLE_FEASIBILITY_GATE=${gate_status} python=${PYTHON_CMD} db_path=${report_db_path} no_fetch=yes"
exit "$status"
