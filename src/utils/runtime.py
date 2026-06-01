from __future__ import annotations

import os


NUMERIC_RUNTIME_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "LOKY_MAX_CPU_COUNT": "1",
    "OMP_WAIT_POLICY": "PASSIVE",
    "KMP_BLOCKTIME": "0",
}


def configure_numeric_runtime() -> None:
    for name, value in NUMERIC_RUNTIME_ENV.items():
        os.environ.setdefault(name, value)
