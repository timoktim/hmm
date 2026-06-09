# HSMM Numba Engine

HSMM can use an optional numba backend for the per-sequence Viterbi dynamic programming kernel. The Python engine remains the reference implementation.

Engine modes:

- `python`: always use the reference Python kernel.
- `numba`: require the numba kernel and raise a clear runtime error when unavailable.
- `auto`: prefer numba when it can be imported and executed, otherwise fall back to Python.

The kernel receives NumPy arrays only:

- emission log likelihoods
- log start probabilities
- log transition matrix
- log duration PMF

Pandas frames, model objects, storage handles, and database writers are not passed into the jitted function.

The first numba call includes JIT compilation overhead. Use `warm_hsmm_numba_engine()` in tests or controlled profiling if a warm compile is needed before measuring. Normal imports do not compile the kernel.

Diagnostics are lightweight:

- requested engine
- resolved engine
- fallback reason
- numba availability
- compile warmed status

Walk-forward performance output may include the resolved engine and fallback reason, but DuckDB schema is not migrated by this package.

This package changes runtime execution only. It does not change HSMM model semantics, lifecycle probability interpretation, readiness policy, thresholds, Stage04 validation behavior, or storage schema.
