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
    echo "STAGE04_WP2_BREAK_CASEBOOK=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
DB_PATH="${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}"
CMD=("$PYTHON_CMD" -m src.evaluation.stage04_break_casebook)
if [[ -f "$DB_PATH" ]]; then
  CMD+=(--db "$DB_PATH")
fi

OUTPUT_MD="reports/stage04/stage04_wp2_break_casebook_report.md"
SUMMARY_JSON="reports/stage04/stage04_wp2_break_casebook_report.json"
SAMPLE_CSV="reports/stage04/stage04_wp2_break_casebook_sample.csv"
ANNOTATION_TEMPLATE="reports/stage04/prospective_break_annotation.template.jsonl"
TMP_OUTPUT_DIR=""
if [[ ! -f "$DB_PATH" ]]; then
  TMP_OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stage04_break_casebook.XXXXXX")"
  OUTPUT_MD="$TMP_OUTPUT_DIR/stage04_wp2_break_casebook_report.md"
  SUMMARY_JSON="$TMP_OUTPUT_DIR/stage04_wp2_break_casebook_report.json"
  SAMPLE_CSV="$TMP_OUTPUT_DIR/stage04_wp2_break_casebook_sample.csv"
  ANNOTATION_TEMPLATE="$TMP_OUTPUT_DIR/prospective_break_annotation.template.jsonl"
  trap '[[ -z "$TMP_OUTPUT_DIR" ]] || rm -rf "$TMP_OUTPUT_DIR"' EXIT
fi

set +e
"${CMD[@]}" \
  --split-registry reports/stage04/split_registry.json \
  --wp1-summary reports/stage04/stage04_wp1_break_detector_report.json \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --sample-csv "$SAMPLE_CSV" \
  --annotation-template "$ANNOTATION_TEMPLATE" \
  --no-fetch
status=$?
set -e

casebook_status="blocked"
if [[ -f "$SUMMARY_JSON" ]]; then
  casebook_status="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('status', 'blocked'))" "$SUMMARY_JSON")"
fi

echo "STAGE04_WP2_BREAK_CASEBOOK=${casebook_status} python=${PYTHON_CMD}"
exit "$status"
