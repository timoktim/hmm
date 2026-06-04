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
    echo "STAGE03R_FINAL_GATE=blocked"
    echo "No python executable found. Expected PYTHON_BIN, .venv/bin/python, python, or python3."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
export PYTHON_BIN="$PYTHON_CMD"
export PYTHON="$PYTHON_CMD"
if [[ -x .venv/bin/pytest ]]; then
  export PYTEST_BIN=".venv/bin/pytest"
  export PYTEST=".venv/bin/pytest"
fi

DB_ARGS=()
if [[ -f data/db/a_share_hmm.duckdb ]]; then
  DB_ARGS=(--db data/db/a_share_hmm.duckdb)
fi
FINAL_HOLDOUT_ARGS=()
if [[ -f reports/stage03r/final_holdout_artifact.json ]]; then
  FINAL_HOLDOUT_ARGS=(--final-holdout-artifact reports/stage03r/final_holdout_artifact.json)
fi

CMD=(
  "$PYTHON_CMD" -m src.evaluation.stage03r_final_gate
  --hazard-readiness reports/stage03r/hazard_readiness_matrix_report.json
  --hazard-vs-hsmm reports/stage03r/hazard_vs_hsmm_report.json
  --risk-protocol reports/stage03r/risk_validation_protocol.json
  --data-quality reports/stage03r/data_quality_ci_report.json
  --hazard-verdict reports/stage03r/multi_horizon_hazard_verdict.md
  --output reports/stage03r/stage03r_final_gate_report.md
  --summary-json reports/stage03r/stage03r_final_gate_report.json
  --no-fetch
)
if [[ ${#DB_ARGS[@]} -gt 0 ]]; then
  CMD+=("${DB_ARGS[@]}")
fi
if [[ ${#FINAL_HOLDOUT_ARGS[@]} -gt 0 ]]; then
  CMD+=("${FINAL_HOLDOUT_ARGS[@]}")
fi

set +e
"${CMD[@]}"
status=$?
set -e

gate_value="blocked"
if [[ -f reports/stage03r/stage03r_final_gate_report.json ]]; then
  gate_value="$("$PYTHON_CMD" -c "import json; print(json.load(open('reports/stage03r/stage03r_final_gate_report.json')).get('status', 'blocked'))")"
fi

echo "STAGE03R_FINAL_GATE=${gate_value} python=${PYTHON_CMD}"
exit "$status"
