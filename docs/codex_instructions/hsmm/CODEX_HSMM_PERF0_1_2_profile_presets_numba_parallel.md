# CODEX_HSMM_PERF0_1_2_profile_presets_numba_parallel

Repository: `timoktim/hmm`

Index id: `HSMM-PERF0-1-2-v1`

Work package: `docs/work_packages/hsmm/HSMM_PERF0_1_2_profile_presets_numba_parallel.md`

Suggested branch: `hsmm/perf0-1-2-profile-presets-numba-parallel`

## Instruction

Start from updated `main`. Execute only this work package:

```text
docs/work_packages/hsmm/HSMM_PERF0_1_2_profile_presets_numba_parallel.md
```

## Required outcome

Implement the first HSMM performance optimization bundle:

```text
PERF0: profile matrix and bottleneck attribution
PERF1: maintenance presets and runtime configuration hardening
PERF2: numba / joblib parallel hardening and fallback visibility
```

This is a performance diagnostics and safe-configuration package. It is not an algorithmic semantics change package.

## Boundary reminders

Do not:

```text
change HSMM statistical semantics
add approximate or pruned Viterbi
change duration probability meaning or lifecycle probability meaning
change readiness policy or downstream Stage03V artifacts
train production HSMM models in CI
require private DuckDB for CI
write persistent DuckDB tables in synthetic/profile-only mode
consume prospective holdout
create trading, buy/sell, sizing, recommendation, execution, or portfolio-action outputs
```

Numba/joblib fallback must be explicit in reports. Silent fallback is not acceptable.

Use the return format specified in the work package when opening the PR.
