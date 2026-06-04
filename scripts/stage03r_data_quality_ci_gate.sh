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
DB_ARGS=()
if [[ -f data/db/a_share_hmm.duckdb ]]; then
  DB_ARGS=(--db data/db/a_share_hmm.duckdb)
fi

set +e
"$PYTHON_CMD" -m src.evaluation.stage03r_data_quality_ci \
  "${DB_ARGS[@]}" \
  --hazard-readiness reports/stage03r/hazard_readiness_matrix_report.json \
  --hazard-vs-hsmm reports/stage03r/hazard_vs_hsmm_report.json \
  --risk-protocol reports/stage03r/risk_validation_protocol.json \
  --hazard-verdict reports/stage03r/multi_horizon_hazard_verdict.md \
  --hazard-prediction-sample reports/stage03r/duration_hazard_logistic_predictions_sample.csv \
  --output reports/stage03r/data_quality_ci_report.md \
  --summary-json reports/stage03r/data_quality_ci_report.json \
  --no-fetch
status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo "STAGE03R_DATA_QUALITY_CI_GATE=pass python=${PYTHON_CMD}"
else
  echo "STAGE03R_DATA_QUALITY_CI_GATE=fail python=${PYTHON_CMD}"
fi

exit "$status"
