# Dependency Policy

Index ID: STAGE03PF-AUDIT-A6

## Purpose

Core numerical, data, HMM, database, UI, and external-data dependencies use compatible version ranges so CI and local diagnostics fail early when dependency drift could change probability semantics.

## Compatible Ranges

- `pandas>=2.1,<4.0`
- `numpy>=1.26,<3.0`
- `scipy>=1.11,<2.0`
- `hmmlearn>=0.3.2,<0.4`
- `duckdb>=0.10,<2.0`
- `streamlit>=1.57.0,<2.0`
- `akshare>=1.13,<2.0`

`src.utils.dependency_guard.check_dependency_versions` verifies these ranges and raises `DependencyGuardError` when a dependency is missing or outside the supported range. CI can call `python -m src.utils.dependency_guard` as a startup diagnostic.

`mootdx>=0.11.7,<0.12` is a runtime market-data-source dependency. It is lazily imported by the TDX provider and can fall back to AKShare, so it is intentionally not part of the core numerical dependency guard.

## hmmlearn Private API Guard

Filtered HMM probabilities rely on hmmlearn's private `_compute_log_likelihood` method. Access is centralized in `require_hmmlearn_log_likelihood`; if the method is missing, not callable with the expected observation matrix, or returns an invalid shape, the code raises `HMMPrivateAPIError` instead of returning synthetic or fallback probabilities.

Monitor access is centralized through `monitor_history`, `last_monitor_log_prob`, and `monitor_converged`. Missing `monitor_.history` or `monitor_.converged` returns conservative fallback values without crashing.

## CI Boundary

CI must not require `data/db/a_share_hmm.duckdb`, must not set `ASHARE_HMM_DB_PATH`, and must not fetch external market or constituent data. Stage03 preflight CI coverage is limited to tests that operate on synthetic, temporary, or repo-local fixtures.
