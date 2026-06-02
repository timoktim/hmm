#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

choose_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  elif [[ -x .venv/bin/python ]]; then
    printf '%s\n' ".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
  else
    return 1
  fi
}

choose_pytest() {
  if [[ -n "${PYTEST:-}" ]]; then
    printf '%s\n' "$PYTEST"
  elif command -v pytest >/dev/null 2>&1; then
    printf '%s\n' "pytest"
  elif [[ -x .venv/bin/pytest ]]; then
    printf '%s\n' ".venv/bin/pytest"
  else
    return 1
  fi
}

PYTHON_BIN="$(choose_python)" || {
  echo "CI_SAFE_STAGE01_VALIDATION=fail"
  echo "No python interpreter found. Set PYTHON or create .venv/bin/python."
  exit 2
}

PYTEST_BIN="$(choose_pytest)" || {
  echo "CI_SAFE_STAGE01_VALIDATION=fail"
  echo "No pytest command found. Set PYTEST, install pytest, or create .venv/bin/pytest."
  exit 2
}

unset ASHARE_HMM_DB_PATH

if [[ -f data/db/a_share_hmm.duckdb || -f data/db/a_share_hmm.duckdb.wal ]]; then
  echo "Local DuckDB file exists but is not used by this CI-safe validation."
fi

tracked_db="$(git ls-files -- 'data/db/*.duckdb' 'data/db/*.wal' '*.duckdb' '*.wal')"
if [[ -n "$tracked_db" ]]; then
  echo "CI_SAFE_STAGE01_VALIDATION=fail"
  echo "Tracked DuckDB/WAL artifacts are forbidden:"
  echo "$tracked_db"
  exit 1
fi

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_hmm_confidence.py tests/test_hmm_label_alignment.py tests/test_hmm_churn_dwell.py
"$PYTEST_BIN" -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
"$PYTEST_BIN" -q tests/test_private_path_hygiene.py
bash scripts/check_no_private_paths.sh

echo "CI_SAFE_STAGE01_VALIDATION=pass private_db_required=no external_data_fetch=no"
