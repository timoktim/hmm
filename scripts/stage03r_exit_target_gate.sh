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
    echo "STAGE03R_EXIT_TARGET_GATE=fail"
    echo "No python executable found. Expected python or .venv/bin/python."
    return 1
  fi
}

choose_pytest() {
  if [[ -n "${PYTEST_BIN:-}" ]]; then
    printf '%s\n' "$PYTEST_BIN"
  elif command -v pytest >/dev/null 2>&1; then
    printf '%s\n' "pytest"
  elif [[ -x .venv/bin/pytest ]]; then
    printf '%s\n' ".venv/bin/pytest"
  else
    echo "STAGE03R_EXIT_TARGET_GATE=fail"
    echo "No pytest executable found. Expected pytest or .venv/bin/pytest."
    return 1
  fi
}

PYTHON_CMD="$(choose_python)"
PYTEST_CMD="$(choose_pytest)"
GATE_STATUS=0

run_step() {
  echo "STAGE03R_EXIT_TARGET_GATE_STEP=$*"
  set +e
  "$@"
  local status=$?
  set -e
  if [[ $status -ne 0 ]]; then
    GATE_STATUS=$status
    echo "STAGE03R_EXIT_TARGET_GATE_STEP_FAILED status=${status} command=$*"
  fi
  return 0
}

run_step "$PYTHON_CMD" -m compileall -q src tests
run_step "$PYTEST_CMD" -q tests/test_exit_target_dataset.py tests/test_exit_target_leakage_purge.py

if [[ -f reports/stage03r/exit_target_dataset_v1_sample.csv ]]; then
  AUDIT_TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$AUDIT_TMP_DIR"' EXIT
  run_step "$PYTHON_CMD" -m src.evaluation.exit_target_leakage_audit \
    --dataset reports/stage03r/exit_target_dataset_v1_sample.csv \
    --output "$AUDIT_TMP_DIR/target_leakage_purge_audit.md" \
    --summary-json "$AUDIT_TMP_DIR/target_leakage_purge_audit.json" \
    --strict
fi

run_step bash scripts/check_no_private_paths.sh
run_step bash scripts/validate_stage01_no_private_db.sh

if [[ $GATE_STATUS -eq 0 ]]; then
  echo "STAGE03R_EXIT_TARGET_GATE=pass python=${PYTHON_CMD} pytest=${PYTEST_CMD}"
else
  echo "STAGE03R_EXIT_TARGET_GATE=fail python=${PYTHON_CMD} pytest=${PYTEST_CMD}"
fi

exit "$GATE_STATUS"
