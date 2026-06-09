#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
MODE="${HSMM_BENCHMARK_MODE:-synthetic}"

if [[ -n "${HSMM_BENCHMARK_DB:-}" ]]; then
  MODE="local"
fi

if [[ "$MODE" == "local" ]]; then
  DB_PATH="${HSMM_BENCHMARK_DB:-${ASHARE_HMM_DB_PATH:-}}"
  if [[ -z "$DB_PATH" || ! -f "$DB_PATH" ]]; then
    echo "HSMM_BENCHMARK_STATUS=skipped reason=missing_db"
    exit 0
  fi

  HSMM_PROFILE_DB="$DB_PATH" \
    HSMM_PROFILE_ENGINE="${HSMM_BENCHMARK_ENGINE:-${HSMM_ENGINE:-auto}}" \
    HSMM_PROFILE_START_DATE="${HSMM_BENCHMARK_START_DATE:-20250101}" \
    HSMM_PROFILE_END_DATE="${HSMM_BENCHMARK_END_DATE:-today}" \
    HSMM_PROFILE_N_ITER="${HSMM_BENCHMARK_N_ITER:-10}" \
  HSMM_PROFILE_MAX_DURATION="${HSMM_BENCHMARK_MAX_DURATION:-40}" \
  HSMM_PROFILE_N_JOBS="${HSMM_BENCHMARK_N_JOBS:-1,2,auto}" \
  PYTHON_BIN="$PYTHON_BIN" \
    bash scripts/hsmm_performance_profile.sh
  exit 0
fi

OUTPUT_PATH="${HSMM_BENCHMARK_OUTPUT:-reports/hsmm_diagnostics/benchmark_sample/benchmark_matrix.jsonl}"
export LOKY_MAX_CPU_COUNT="${LOKY_MAX_CPU_COUNT:-${HSMM_BENCHMARK_LOKY_MAX_CPU_COUNT:-2}}"

"$PYTHON_BIN" -m src.models.hsmm_benchmark synthetic \
  --engines "${HSMM_BENCHMARK_ENGINES:-python,auto,numba}" \
  --n-jobs "${HSMM_BENCHMARK_N_JOBS:-1,2,auto}" \
  --n-iter "${HSMM_BENCHMARK_N_ITER:-3}" \
  --max-duration "${HSMM_BENCHMARK_MAX_DURATION:-12}" \
  --n-sequences "${HSMM_BENCHMARK_N_SEQUENCES:-4}" \
  --sequence-length "${HSMM_BENCHMARK_SEQUENCE_LENGTH:-32}" \
  --output "$OUTPUT_PATH"
