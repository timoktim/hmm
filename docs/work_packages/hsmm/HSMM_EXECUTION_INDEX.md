# HSMM_EXECUTION_INDEX

Status: active
Area: HSMM performance optimization
Active package: HSMM-PERF0-1-2-v1

## Purpose

This index tracks HSMM performance optimization work independently from Stage03V business-model sequencing.

The first active bundle combines:

```text
PERF0: Profile matrix and bottleneck attribution
PERF1: Maintenance presets and runtime configuration hardening
PERF2: Numba / joblib parallel hardening and fallback visibility
```

The goal is to make HSMM runtime behavior measurable and configurable before considering deeper algorithmic changes.

## Route Anchors

- `docs/runtime/HSMM_PERFORMANCE.md`
- `src/models/hsmm_core.py`
- `src/models/hsmm_model.py`
- `src/models/hsmm_walk_forward.py`
- `scripts/hsmm_performance_profile.sh`
- `scripts/check_hsmm_numba_engine.sh`
- `scripts/hsmm_benchmark_matrix.sh`
- `docs/work_packages/hsmm/HSMM_PERF0_1_2_profile_presets_numba_parallel.md`
- `docs/codex_instructions/hsmm/CODEX_HSMM_PERF0_1_2_profile_presets_numba_parallel.md`

## Package Sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| HSMM-PERF0-1-2-v1 | Profile Matrix, Maintenance Presets, Numba/Parallel Hardening | active | hsmm/perf0-1-2-profile-presets-numba-parallel | attribute HSMM runtime bottlenecks, define safe presets, expose acceleration fallback state |
| HSMM-PERF3 | Snapshot Cache / Prefix-DP Reuse | blocked_until_perf0_1_2_accepted | TBD | optimize repeated lifecycle snapshot decode only if profile shows snapshot decode is dominant |
| HSMM-PERF4 | Streaming Parameter Update | blocked_until_perf0_1_2_accepted | TBD | optimize fit update path only if profile shows update time is material |
| HSMM-PERF5 | Approximate / Pruned Viterbi | blocked_pending_explicit_approval | TBD | optional high-risk approximate engine, not allowed unless separately pre-registered |
| HSMM-PERF6 | Maintenance Cadence and Reuse Strategy | blocked_until_perf0_1_2_accepted | TBD | define daily decode, monthly retrain, and full research maintenance cadence |

## Execution Rules

1. Only HSMM-PERF0-1-2-v1 is executable in the current HSMM performance sequence.
2. This sequence must not change HSMM statistical semantics.
3. This sequence must not add approximate/pruned Viterbi until a later explicit work package authorizes it.
4. Synthetic profiling must not require private DuckDB.
5. Local DB profiling must be explicit and must not fail CI when the private DB is absent.
6. Profile-only mode must not write production HSMM model rows.
7. Numba/joblib fallback must be visible in diagnostics and reports.
8. No Stage03V target/model/readiness artifacts may be modified.
9. No prospective holdout may be consumed.
10. No trading, buy/sell, sizing, recommendation, execution, or portfolio-action outputs may be created.

## Expected Deliverables for HSMM-PERF0-1-2-v1

- `src/evaluation/hsmm_performance_matrix.py`
- `src/models/hsmm_performance_presets.py` if useful
- `configs/hsmm_performance_presets_v1.yaml`
- `scripts/hsmm_perf0_1_2_gate.sh`
- `tests/test_hsmm_performance_matrix.py`
- `reports/hsmm_diagnostics/hsmm_performance_matrix_report.md`
- `reports/hsmm_diagnostics/hsmm_performance_matrix_report.json`
- `reports/hsmm_diagnostics/hsmm_performance_matrix_summary.csv`
- updates to `docs/runtime/HSMM_PERFORMANCE.md`

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-12 | Activated HSMM-PERF0-1-2-v1 profile, preset, and acceleration-hardening bundle. | ChatGPT |
