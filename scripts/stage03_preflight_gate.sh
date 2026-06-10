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
    echo "STAGE03_PREFLIGHT_GATE=fail"
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
    echo "STAGE03_PREFLIGHT_GATE=fail"
    echo "No pytest executable found. Expected PYTEST_BIN, .venv/bin/pytest, or pytest."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
PYTEST_CMD="$(choose_pytest)"
GATE_STATUS=0

run_step() {
  echo "STAGE03_PREFLIGHT_GATE_STEP=$*"
  set +e
  "$@"
  local status=$?
  set -e
  if [[ $status -ne 0 ]]; then
    GATE_STATUS=$status
    echo "STAGE03_PREFLIGHT_GATE_STEP_FAILED status=${status} command=$*"
  fi
  return 0
}

run_step "$PYTHON_CMD" -m compileall -q src tests
run_step "$PYTEST_CMD" -q \
  tests/test_lineage_hash_contract.py \
  tests/test_hmm_walk_forward_cache_contract.py \
  tests/test_hmm_cached_state_feature_guard.py \
  tests/test_hsmm_lifecycle_asof_targets.py \
  tests/test_hsmm_duration_tail_semantics.py \
  tests/test_hsmm_prefix_causality.py \
  tests/test_hsmm_run_atomicity.py \
  tests/test_hsmm_cascade_cleanup.py \
  tests/test_probability_readiness_lineage.py \
  tests/test_probability_gate_strictness.py \
  tests/test_ui_readiness_selection.py \
  tests/test_analysis_cache_selection.py \
  tests/test_universe_data_lineage.py \
  tests/test_evidence_registry_contract.py

run_step bash scripts/check_no_private_paths.sh
run_step bash scripts/validate_stage01_no_private_db.sh
run_step bash scripts/stage03r_data_quality_ci_gate.sh

if [[ $GATE_STATUS -eq 0 ]]; then
  echo "STAGE03_PREFLIGHT_GATE=pass python=${PYTHON_CMD} pytest=${PYTEST_CMD}"
else
  echo "STAGE03_PREFLIGHT_GATE=fail python=${PYTHON_CMD} pytest=${PYTEST_CMD}"
fi

exit "$GATE_STATUS"
