#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"

if [[ "${HSMM_ENGINE_REQUIRED:-0}" == "1" ]]; then
  "$PYTHON_BIN" -m src.models.hsmm_benchmark check-numba --required
else
  "$PYTHON_BIN" -m src.models.hsmm_benchmark check-numba
fi
