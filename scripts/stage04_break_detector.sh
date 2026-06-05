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
    echo "STAGE04_WP1_BREAK_DETECTOR=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
CMD=("$PYTHON_CMD" -m src.evaluation.stage04_break_detector)
if [[ -f data/db/a_share_hmm.duckdb ]]; then
  CMD+=(--db data/db/a_share_hmm.duckdb)
fi

OUTPUT_MD="reports/stage04/stage04_wp1_break_detector_report.md"
SUMMARY_JSON="reports/stage04/stage04_wp1_break_detector_report.json"
SAMPLE_CSV="reports/stage04/stage04_wp1_break_detector_sample.csv"
TMP_OUTPUT_DIR=""
if [[ ! -f data/db/a_share_hmm.duckdb ]]; then
  TMP_OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stage04_break_detector.XXXXXX")"
  OUTPUT_MD="$TMP_OUTPUT_DIR/stage04_wp1_break_detector_report.md"
  SUMMARY_JSON="$TMP_OUTPUT_DIR/stage04_wp1_break_detector_report.json"
  SAMPLE_CSV="$TMP_OUTPUT_DIR/stage04_wp1_break_detector_sample.csv"
  trap '[[ -z "$TMP_OUTPUT_DIR" ]] || rm -rf "$TMP_OUTPUT_DIR"' EXIT
fi

set +e
"${CMD[@]}" \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --sample-csv "$SAMPLE_CSV" \
  --no-fetch
status=$?
set -e

detector_status="blocked"
if [[ -f "$SUMMARY_JSON" ]]; then
  detector_status="$("$PYTHON_CMD" -c "import json, sys; print(json.load(open(sys.argv[1])).get('status', 'blocked'))" "$SUMMARY_JSON")"
fi

echo "STAGE04_WP1_BREAK_DETECTOR=${detector_status} python=${PYTHON_CMD}"
exit "$status"
