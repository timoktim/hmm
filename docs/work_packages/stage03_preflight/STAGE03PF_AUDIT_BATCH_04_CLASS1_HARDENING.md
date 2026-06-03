# STAGE03PF_AUDIT_BATCH_04_CLASS1_HARDENING

Purpose: integrate high-value audit findings that still block safe Stage03 entry after WP0-WP13 implementation and WP0A OHLCV ingestion validation.

This is still preflight hardening, not Stage03 model work. Do not implement Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or new training algorithms in this batch.

## Why this batch exists

The 2026-06-03 audit identified several high-impact correctness gaps. D1 OHLCV ingestion validation is already handled separately by WP0A. This batch handles the remaining high-value items:

- H1/H2: HSMM exit calibration target mismatch and horizon leakage.
- H3/H4/H8/H9: HSMM duration tail and right-censoring semantics.
- D2: market breadth local_sample coverage semantics.
- D3/D8/D12 subset: custom basket index semantics and low-coverage handling.
- F1/F2: backtest execution price semantics and in-sample evaluation guard.
- E1/S5/E2: CI expansion and dependency/private API guard.

## Execution order

Recommended order:

```text
A1 -> A2
A3 and A4 can run in parallel after A1 starts
A5 after A3 if it touches shared market/feature files
A6 can run in parallel with A3/A4, but merge after A1/A2 if CI matrix changes broadly
```

Never run more than three active PRs at once.

## Shared rules

- Start from updated `main`.
- One PR per package.
- No external data fetch.
- No DuckDB/WAL commit.
- Synthetic tests required.
- If a package uses local DB, read `docs/runtime/LOCAL_DB_HANDOFF.md` first.
- Any in-sample evaluation must be explicit and research-only.
- Any probability readiness mismatch must fail closed.

---

## A1 HSMM Exit Calibration Target and Horizon Safety

Index ID: STAGE03PF-AUDIT-A1
Priority: Class 1 / blocking
Branch: `stage03pf/a1-hsmm-exit-calibration-target-safety`

### Goal

Fix HSMM exit calibration target mismatch and horizon leakage. The audit found that raw `p_exit` is state-id duration based while actual exit may be label-change based, and calibration training labels can peek beyond `train_end` by up to horizon days.

### Allowed files

```text
src/evaluation/hsmm_exit_calibration.py
src/evaluation/hsmm_exit_targets.py
src/evaluation/hsmm_diagnostics.py
src/evaluation/hsmm_lifecycle_probability_report.py
tests/test_hsmm_exit_calibration_target_alignment.py
tests/test_hsmm_exit_calibration_horizon_split.py
```

### Tasks

1. Add explicit `target_type` support:

```text
state_id_exit
display_label_exit
```

2. Ensure raw p_exit basis and actual exit label use the same `target_type`.
3. Calibration training rows must satisfy:

```text
trade_date + horizon <= train_end_date
realized_exit_date <= train_end_date for observed_positive
otherwise censored/unknown and excluded from calibration training
```

4. `fit_empirical_exit_calibrator(train_end_date=None)` must fail closed by default, unless `allow_in_sample=True` is explicitly passed.
5. Calibration report must record:

```text
target_type
train_label_cutoff_policy
censored_row_count
excluded_post_train_horizon_count
allow_in_sample
```

6. Calibration failure must not produce `usable_probability`.

### Tests

- Adjacent state_id with same display label shows different `state_id_exit` and `display_label_exit` targets.
- raw p_exit target_type equals actual exit target_type.
- Horizon label beyond train_end is excluded.
- Exit realized after train_end is not a positive training label.
- `train_end_date=None` fails closed unless `allow_in_sample=True`.
- failed calibration leaves readiness non-usable.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_exit_calibration_target_alignment.py tests/test_hsmm_exit_calibration_horizon_split.py
pytest -q tests/test_hsmm_lifecycle_asof_targets.py tests/test_probability_gate_strictness.py
```

### Return format

```text
WP: STAGE03PF-AUDIT-A1
status: pass / partial / fail
branch: stage03pf/a1-hsmm-exit-calibration-target-safety
PR: ...
commands run:
- ...
calibration:
- target_type aligned: yes/no
- horizon leakage blocked: yes/no
- allow_in_sample explicit: yes/no
- failed calibration non-usable: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## A2 HSMM Duration Tail and Right-Censoring Semantics

Index ID: STAGE03PF-AUDIT-A2
Priority: Class 1 / blocking
Branch: `stage03pf/a2-hsmm-duration-tail-censoring`

### Goal

Repair duration PMF and tail semantics so truncated/right-censored duration evidence does not create false certainty such as `p_exit=1.0` at support boundary.

### Allowed files

```text
src/models/hsmm_model.py
src/models/hsmm_walk_forward.py
src/evaluation/hsmm_display_lifecycle.py
tests/test_hsmm_duration_right_censoring.py
tests/test_hsmm_duration_tail_semantics.py
tests/test_hsmm_prefix_causality.py
```

### Tasks

1. Use `is_right_censored` information where available in duration fitting/profile generation.
2. Ensure `age >= max_duration` does not create deterministic `p_exit=1.0` from truncation artifact.
3. Beyond support output must be status-coded:

```text
beyond_duration_support
tail_censored
unavailable
```

4. `duration_percentile` can reach 1.0 only with explicit `duration_percentile_status='beyond_support'` or equivalent.
5. Prefix causality must remain locked: identical prefix with different future suffix yields identical prefix snapshots.
6. Rows with undefined tail probability must not be calibrated through global fallback into a precise numeric exit probability.

### Tests

- right-censored episodes do not inflate completed duration PMF.
- `age=max_duration` and `age>max_duration` do not produce unconditional `p_exit=1.0` without status.
- lifecycle output shows unavailable/tail-censored instead of 100% exit.
- prefix snapshot unchanged by future suffix.
- NaN raw_p_exit rows do not receive global fallback calibrated probability as usable.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_duration_right_censoring.py tests/test_hsmm_duration_tail_semantics.py tests/test_hsmm_prefix_causality.py
pytest -q tests/test_probability_gate_strictness.py
```

### Return format

```text
WP: STAGE03PF-AUDIT-A2
status: pass / partial / fail
branch: stage03pf/a2-hsmm-duration-tail-censoring
PR: ...
commands run:
- ...
duration semantics:
- right censoring handled: yes/no
- boundary p_exit not deterministic: yes/no
- undefined tail not calibrated as usable: yes/no
- prefix causality locked: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## A3 Market Breadth Coverage Semantics

Index ID: STAGE03PF-AUDIT-A3
Priority: Class 1 / blocking if market features are used in Stage03
Branch: `stage03pf/a3-market-breadth-coverage-semantics`

### Goal

Correct `local_sample` coverage semantics. The audit found local sample coverage can self-report near 1.0 because denominator is local observed total, not full market expected count.

### Allowed files

```text
src/data_pipeline/market_updater.py
src/features/market_features.py
src/models/market_hmm.py
src/ui/market_regime_page.py
tests/test_market_breadth_coverage_semantics.py
```

### Tasks

1. Add explicit `coverage_mode`:

```text
full_market
local_sample
unknown
```

2. Do not call `effective_count / total_count` a full-market coverage ratio under `local_sample`.
3. If full-market `expected_count` is unavailable, full-market coverage must be null/unavailable.
4. Add separate field if needed:

```text
local_sample_internal_coverage
full_market_coverage_ratio
coverage_mode
coverage_warning
```

5. Downstream feature/readiness must distinguish local sample from full-market coverage.
6. UI must state local sample is not full A-share coverage.
7. Avoid all-or-nothing feature disabling for an entire training range due to one-day coverage warnings; prefer date-aware or mode-aware handling.

### Tests

- local_sample does not report fake full-market coverage.
- missing expected_count yields full-market coverage unavailable.
- UI/report includes local_sample warning.
- market_hmm does not treat local_sample coverage as full_market pass.
- one bad coverage day does not disable the whole historical feature range unless strict policy is enabled.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_market_breadth_coverage_semantics.py
```

### Return format

```text
WP: STAGE03PF-AUDIT-A3
status: pass / partial / fail
branch: stage03pf/a3-market-breadth-coverage-semantics
PR: ...
commands run:
- ...
coverage semantics:
- local_sample not fake full coverage: yes/no
- UI warning present: yes/no
- downstream mode-aware: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## A4 Custom Basket Index Semantics and Low-Coverage Guard

Index ID: STAGE03PF-AUDIT-A4
Priority: Class 1 / blocking if custom baskets are used in Stage03 universe
Branch: `stage03pf/a4-custom-basket-index-semantics`

### Goal

Fix custom basket index semantics when members are suspended or missing. The audit found effective-member re-normalization can unintentionally redistribute weights and hide low coverage.

### Allowed files

```text
src/features/custom_basket_features.py
src/data_pipeline/storage.py
src/ui/universe_manager.py
tests/test_custom_basket_index_semantics.py
```

### Tasks

1. Introduce explicit index policies:

```text
dynamic_available_members
fixed_weight_zero_return
```

2. `fixed_weight_zero_return` keeps original weights and treats missing/suspended member daily return as 0.
3. `dynamic_available_members` may remain but must be explicit in output and UI.
4. Output fields must include:

```text
index_method_effective
coverage_ratio
missing_member_count
low_coverage_warning
membership_policy
```

5. Low coverage warning must be recorded; `strict=True` should block insert/generation.
6. Fix stock code formatting mismatch, ensuring source codes and basket member codes use consistent zfill logic.

### Tests

- fixed policy does not redistribute suspended member weight.
- dynamic and fixed policies produce different results on missing member day.
- coverage below threshold produces warning.
- strict low coverage blocks output/upsert.
- zfilled stock codes join correctly.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_custom_basket_index_semantics.py
```

### Return format

```text
WP: STAGE03PF-AUDIT-A4
status: pass / partial / fail
branch: stage03pf/a4-custom-basket-index-semantics
PR: ...
commands run:
- ...
custom basket:
- fixed_weight_zero_return implemented: yes/no
- dynamic policy explicit: yes/no
- low coverage warning/strict block: yes/no
- stock code normalization fixed: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## A5 Backtest and Evaluation Causal Semantics

Index ID: STAGE03PF-AUDIT-A5
Priority: Class 1 / blocking for any Stage03 decision/evaluation work
Branch: `stage03pf/a5-backtest-evaluation-causal-semantics`

### Goal

Fix execution timing ambiguity and prevent sample-in evaluation from being silently used as causal evidence.

### Allowed files

```text
src/backtest/sector_rotation.py
src/evaluation/model_evaluation.py
src/ui/model_evaluation_page.py
tests/test_backtest_execution_price_semantics.py
tests/test_model_evaluation_causal_guard.py
```

### Tasks

1. Make execution timing explicit:

```text
execution_price_policy
execution_timing
entry_day_return_policy
cost_policy
```

2. Default open execution must not silently count unavailable entry-day intraday return.
3. If open-to-close entry day return is retained, it must be explicitly requested and documented.
4. `evaluate_forward_returns` must require `evaluation_mode`.
5. In-sample mode must return:

```text
evidence_level=exploratory
readiness_status=research_only
state_source=in_sample_explanation
```

6. Causal evaluation mode must require causal cache metadata or `state_source=causal_walk_forward` and matching readiness evidence.
7. UI warning cannot be the only guard; function layer must fail closed.

### Tests

- open execution does not count entry-day intraday return by default.
- execution policy is recorded in report/result.
- evaluate_forward_returns without mode fails closed.
- in-sample mode is explicitly research_only.
- causal mode without causal cache is blocked/research_only.
- causal mode rejects in-sample states.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_backtest_execution_price_semantics.py tests/test_model_evaluation_causal_guard.py
```

### Return format

```text
WP: STAGE03PF-AUDIT-A5
status: pass / partial / fail
branch: stage03pf/a5-backtest-evaluation-causal-semantics
PR: ...
commands run:
- ...
evaluation semantics:
- execution timing explicit: yes/no
- in-sample fails closed or research-only: yes/no
- causal cache required for causal mode: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## A6 CI Expansion and Dependency / Private API Guard

Index ID: STAGE03PF-AUDIT-A6
Priority: Class 1 / blocking for stable Stage03 development environment
Branch: `stage03pf/a6-ci-dependency-private-api-guard`

### Goal

Expand CI beyond the current narrow smoke path and prevent dependency/private API drift from silently breaking causal probability code.

### Allowed files

```text
.github/workflows/ci.yml
requirements.txt
src/models/hmm_model.py
src/models/market_hmm.py
src/utils/dependency_guard.py
tests/test_dependency_guard.py
tests/test_hmm_private_api_guard.py
docs/validation/DEPENDENCY_POLICY.md
```

### Tasks

1. Add upper bounds or compatible ranges for core dependencies:

```text
pandas
numpy
scipy
hmmlearn
duckdb
streamlit
akshare
```

2. Add dependency guard that can be called in CI or startup diagnostics.
3. Centralize hmmlearn private API usage, especially `_compute_log_likelihood`.
4. If private API is absent, fail with explicit error; do not return bogus probabilities.
5. Guard `monitor_.history` and `monitor_.converged` access with compatibility wrapper.
6. Expand CI to include key Stage03 preflight tests that do not need private DB:

```text
lineage/cache contract
HSMM as-of/run atomicity/cascade/tail
probability readiness
UI/analysis selection
evidence registry
OHLCV validation
private path hygiene
```

7. CI must still not require private DB.

### Tests

- dependency version outside allowed range fails guard.
- missing hmmlearn private log-likelihood API fails explicitly.
- missing monitor attributes return unknown/fallback without crashing.
- CI script still passes without private DB.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_dependency_guard.py tests/test_hmm_private_api_guard.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

### Return format

```text
WP: STAGE03PF-AUDIT-A6
status: pass / partial / fail
branch: stage03pf/a6-ci-dependency-private-api-guard
PR: ...
commands run:
- ...
CI/dependencies:
- dependency upper bounds added: yes/no
- private API guarded: yes/no
- CI expanded without private DB: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```