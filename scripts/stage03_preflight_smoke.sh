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
    echo "STAGE03_PREFLIGHT_SMOKE=fail"
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
    echo "STAGE03_PREFLIGHT_SMOKE=fail"
    echo "No pytest executable found. Expected PYTEST_BIN, .venv/bin/pytest, or pytest."
    return 1
  fi
}

PYTHON_BIN="$(choose_python)"
PYTEST_BIN="$(choose_pytest)"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_hsmm_*.py tests/test_lifecycle_*.py

echo "STAGE03_PREFLIGHT_SMOKE=pass python=${PYTHON_BIN} pytest=${PYTEST_BIN}"
