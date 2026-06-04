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
    echo "STAGE03R_FINAL_HOLDOUT_ARTIFACT=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
DB_ARGS=()
if [[ -f data/db/a_share_hmm.duckdb ]]; then
  DB_ARGS=(--db data/db/a_share_hmm.duckdb)
fi

set +e
"$PYTHON_CMD" -m src.evaluation.final_holdout_artifact \
  "${DB_ARGS[@]}" \
  --hazard-readiness reports/stage03r/hazard_readiness_matrix_report.json \
  --risk-protocol reports/stage03r/risk_validation_protocol.json \
  --data-quality reports/stage03r/data_quality_ci_report.json \
  --output reports/stage03r/final_holdout_artifact.md \
  --summary-json reports/stage03r/final_holdout_artifact.json \
  --no-fetch
status=$?
set -e

gate_value="blocked"
if [[ -f reports/stage03r/final_holdout_artifact.json ]]; then
  gate_value="$("$PYTHON_CMD" -c "import json; print(json.load(open('reports/stage03r/final_holdout_artifact.json')).get('status', 'blocked'))")"
fi

echo "STAGE03R_FINAL_HOLDOUT_ARTIFACT=${gate_value} python=${PYTHON_CMD}"
exit "$status"
