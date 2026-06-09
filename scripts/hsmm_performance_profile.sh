#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${HSMM_PROFILE_DB:-${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}}"
START_DATE="${HSMM_PROFILE_START_DATE:-20250101}"
END_DATE="${HSMM_PROFILE_END_DATE:-today}"
HSMM_ENGINE_VALUE="${HSMM_PROFILE_ENGINE:-${HSMM_ENGINE:-auto}}"
N_JOBS="${HSMM_PROFILE_N_JOBS:-${HSMM_N_JOBS:-auto}}"
FIT_N_JOBS="${HSMM_PROFILE_FIT_N_JOBS:-${HSMM_FIT_N_JOBS:-$N_JOBS}}"
MAX_DURATION="${HSMM_PROFILE_MAX_DURATION:-${HSMM_MAX_DURATION:-40}}"
N_ITER="${HSMM_PROFILE_N_ITER:-${HSMM_N_ITER:-10}}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "HSMM_PROFILE_STATUS=skipped reason=missing_db db_path=$DB_PATH"
  exit 0
fi

cmd=(
  "$PYTHON_BIN" -m src.models.hsmm_walk_forward
  --db "$DB_PATH"
  --start-date "$START_DATE"
  --end-date "$END_DATE"
  --profile-only
  --snapshot-decode-mode prefix
  --hsmm-engine "$HSMM_ENGINE_VALUE"
  --n-jobs "$N_JOBS"
  --fit-n-jobs "$FIT_N_JOBS"
  --max-duration "$MAX_DURATION"
  --n-iter "$N_ITER"
)

if [[ -n "${HSMM_PROFILE_RUN_ID:-}" ]]; then
  cmd+=(--run-id "$HSMM_PROFILE_RUN_ID")
fi

"${cmd[@]}"
