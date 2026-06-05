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
    echo "STAGE04_WP5_ANNOTATION_OPERATIONS=blocked operations_status=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
SUMMARY_JSON="reports/stage04/stage04_wp5_annotation_operations_report.json"

set +e
"$PYTHON_CMD" -m src.evaluation.stage04_annotation_operations \
  --split-registry reports/stage04/split_registry.json \
  --wp3-report reports/stage04/stage04_wp3_annotation_label_gate_report.json \
  --wp4-report reports/stage04/stage04_wp4_annotation_capture_report.json \
  --annotation-ledger reports/stage04/prospective_break_annotation.local.jsonl \
  --output reports/stage04/stage04_wp5_annotation_operations_report.md \
  --summary-json "$SUMMARY_JSON" \
  --sample-csv reports/stage04/stage04_wp5_annotation_operations_sample.csv \
  --no-fetch
status=$?
set -e

summary_status="blocked"
operations_status="blocked"
if [[ -f "$SUMMARY_JSON" ]]; then
  summary_status="$("$PYTHON_CMD" -c "import json, sys; p=json.load(open(sys.argv[1])); print(p.get('status', 'blocked'))" "$SUMMARY_JSON")"
  operations_status="$("$PYTHON_CMD" -c "import json, sys; p=json.load(open(sys.argv[1])); print(p.get('operations_status', 'blocked'))" "$SUMMARY_JSON")"
fi

echo "STAGE04_WP5_ANNOTATION_OPERATIONS=${summary_status} operations_status=${operations_status} python=${PYTHON_CMD}"
exit "$status"
