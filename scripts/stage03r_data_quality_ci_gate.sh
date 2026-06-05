#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

choose_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  elif [[ -x .venv/bin/python ]]; then
    printf '%s\n' ".venv/bin/python"
  else
    echo "STAGE03R_DATA_QUALITY_CI_GATE=fail"
    echo "No python executable found. Expected python or .venv/bin/python."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
CMD=("$PYTHON_CMD" -m src.evaluation.stage03r_data_quality_ci)
if [[ -f data/db/a_share_hmm.duckdb ]]; then
  CMD+=(--db data/db/a_share_hmm.duckdb)
fi
OUTPUT_MD="reports/stage03r/data_quality_ci_report.md"
SUMMARY_JSON="reports/stage03r/data_quality_ci_report.json"
TMP_OUTPUT_DIR=""
if [[ ! -f data/db/a_share_hmm.duckdb ]]; then
  TMP_OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stage03r_data_quality_ci.XXXXXX")"
  OUTPUT_MD="$TMP_OUTPUT_DIR/data_quality_ci_report.md"
  SUMMARY_JSON="$TMP_OUTPUT_DIR/data_quality_ci_report.json"
  trap '[[ -z "$TMP_OUTPUT_DIR" ]] || rm -rf "$TMP_OUTPUT_DIR"' EXIT
fi

set +e
"${CMD[@]}" \
  --hazard-readiness reports/stage03r/hazard_readiness_matrix_report.json \
  --hazard-vs-hsmm reports/stage03r/hazard_vs_hsmm_report.json \
  --risk-protocol reports/stage03r/risk_validation_protocol.json \
  --hazard-verdict reports/stage03r/multi_horizon_hazard_verdict.md \
  --hazard-prediction-sample reports/stage03r/duration_hazard_logistic_predictions_sample.csv \
  --output "$OUTPUT_MD" \
  --summary-json "$SUMMARY_JSON" \
  --no-fetch
status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo "STAGE03R_DATA_QUALITY_CI_GATE=pass python=${PYTHON_CMD}"
else
  echo "STAGE03R_DATA_QUALITY_CI_GATE=fail python=${PYTHON_CMD}"
fi

exit "$status"
