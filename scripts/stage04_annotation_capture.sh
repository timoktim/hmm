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
    echo "STAGE04_WP4_ANNOTATION_CAPTURE=blocked capture_status=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
MODE="${STAGE04_ANNOTATION_CAPTURE_MODE:-dry-run}"
SOURCE="${STAGE04_ANNOTATION_CAPTURE_SOURCE:-latest_wp1}"

args=(
  -m src.evaluation.stage04_annotation_capture
  --split-registry reports/stage04/split_registry.json
  --wp1-report reports/stage04/stage04_wp1_break_detector_report.json
  --wp2-report reports/stage04/stage04_wp2_break_casebook_report.json
  --wp3-report reports/stage04/stage04_wp3_annotation_label_gate_report.json
  --annotation-ledger reports/stage04/prospective_break_annotation.local.jsonl
  --output reports/stage04/stage04_wp4_annotation_capture_report.md
  --summary-json reports/stage04/stage04_wp4_annotation_capture_report.json
  --sample-jsonl reports/stage04/stage04_wp4_annotation_capture_sample.jsonl
  --mode "$MODE"
  --source "$SOURCE"
  --no-fetch
)

if [[ -n "${STAGE04_ANNOTATION_EPISODE_ID:-}" ]]; then
  args+=(--episode-id "$STAGE04_ANNOTATION_EPISODE_ID")
fi
if [[ -n "${STAGE04_ANNOTATION_DIAGNOSTIC_TRADE_DATE:-}" ]]; then
  args+=(--diagnostic-trade-date "$STAGE04_ANNOTATION_DIAGNOSTIC_TRADE_DATE")
fi
if [[ -n "${STAGE04_ANNOTATION_BREAK_WARNING_LEVEL:-}" ]]; then
  args+=(--break-warning-level "$STAGE04_ANNOTATION_BREAK_WARNING_LEVEL")
fi
if [[ -n "${STAGE04_ANNOTATION_COMPONENT_STRESS_LABELS:-}" ]]; then
  args+=(--component-stress-labels "$STAGE04_ANNOTATION_COMPONENT_STRESS_LABELS")
fi
if [[ -n "${STAGE04_ANNOTATION_AVAILABLE_COMPONENT_COUNT:-}" ]]; then
  args+=(--available-component-count "$STAGE04_ANNOTATION_AVAILABLE_COMPONENT_COUNT")
fi
if [[ -n "${STAGE04_ANNOTATION_ANALYST_ANNOTATION:-}" ]]; then
  args+=(--analyst-annotation "$STAGE04_ANNOTATION_ANALYST_ANNOTATION")
fi
if [[ -n "${STAGE04_ANNOTATION_OBSERVED_MARKET_CONTEXT:-}" ]]; then
  args+=(--observed-market-context "$STAGE04_ANNOTATION_OBSERVED_MARKET_CONTEXT")
fi
if [[ -n "${STAGE04_ANNOTATION_FOLLOWUP_REQUIRED:-}" ]]; then
  args+=(--followup-required "$STAGE04_ANNOTATION_FOLLOWUP_REQUIRED")
fi
if [[ -n "${STAGE04_ANNOTATION_DATE:-}" ]]; then
  args+=(--annotation-date "$STAGE04_ANNOTATION_DATE")
fi

if [[ "$#" -gt 0 ]]; then
  args+=("$@")
fi

set +e
"$PYTHON_CMD" "${args[@]}"
status=$?
set -e

capture_status="blocked"
summary_status="blocked"
SUMMARY_JSON="reports/stage04/stage04_wp4_annotation_capture_report.json"
if [[ -f "$SUMMARY_JSON" ]]; then
  summary_status="$("$PYTHON_CMD" -c "import json, sys; p=json.load(open(sys.argv[1])); print(p.get('status', 'blocked'))" "$SUMMARY_JSON")"
  capture_status="$("$PYTHON_CMD" -c "import json, sys; p=json.load(open(sys.argv[1])); print(p.get('capture_status', 'blocked'))" "$SUMMARY_JSON")"
fi

echo "STAGE04_WP4_ANNOTATION_CAPTURE=${summary_status} capture_status=${capture_status} python=${PYTHON_CMD}"
exit "$status"
