#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

choose_python() {
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  elif [[ -x .venv/bin/python ]]; then
    printf '%s\n' ".venv/bin/python"
  else
    echo "STAGE03_PREFLIGHT_SMOKE=fail"
    echo "No python executable found. Expected python or .venv/bin/python."
    return 1
  fi
}

choose_pytest() {
  if command -v pytest >/dev/null 2>&1; then
    printf '%s\n' "pytest"
  elif [[ -x .venv/bin/pytest ]]; then
    printf '%s\n' ".venv/bin/pytest"
  else
    echo "STAGE03_PREFLIGHT_SMOKE=fail"
    echo "No pytest executable found. Expected pytest or .venv/bin/pytest."
    return 1
  fi
}

PYTHON_BIN="$(choose_python)"
PYTEST_BIN="$(choose_pytest)"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_hsmm_*.py tests/test_lifecycle_*.py

echo "STAGE03_PREFLIGHT_SMOKE=pass python=${PYTHON_BIN} pytest=${PYTEST_BIN}"
