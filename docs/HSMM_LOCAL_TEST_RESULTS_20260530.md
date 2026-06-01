# HSMM Local Test Results

生成日期：2026-05-30

## 1. Git / code version

- commit hash: not available
- branch: not available
- note: 当前目录不是 git repository。

## 2. Environment

- python version: 3.12.13
- duckdb version: 1.5.3
- db path: `data/db/a_share_hmm.duckdb`
- data range: 2020-01-02 至 2026-05-29
- sector count in `sector_ohlcv`: 466
- trade day count in `sector_ohlcv`: 1551

## 3. Unit and integration tests

- compileall: passed
- `pytest -q tests/test_hsmm_*.py`: 24 passed
- `pytest -q`: 139 passed, 2 skipped, 25 warnings
- `pytest -q -m "not slow"`: 139 passed, 2 deselected, 25 warnings
- `pytest -q -m slow`: 2 passed, 139 deselected
- failed tests: none
- warnings: existing NumPy/Pandas constant-input warnings in `tests/test_signal_validation.py`

## 4. Schema migration

- passed: yes
- idempotent: yes, `DuckDBStorage.init_schema()` was executed twice successfully
- missing fields: none

Checked tables and new fields:

- `hsmm_state_daily`
  - `model_state_age_days`
  - `label_state_age_days`
  - `duration_model_age_days`
  - `display_state_age_days`
  - `raw_p_exit_1d`, `raw_p_exit_3d`, `raw_p_exit_5d`, `raw_p_exit_10d`, `raw_p_exit_20d`
  - `calibrated_p_exit_1d`, `calibrated_p_exit_3d`, `calibrated_p_exit_5d`, `calibrated_p_exit_10d`, `calibrated_p_exit_20d`
- `hsmm_state_episodes`
  - `is_left_censored`
  - `left_censor_reason`
  - `is_right_censored`
  - `right_censor_reason`
- `hsmm_model_checkpoints`
  - `params_hash`
  - `config_hash`

## 5. Rerun cleanup test

- passed: yes
- run_id: `hsmm_rerun_cleanup_test`
- after long run then short rerun:
  - min trade_date: 2026-05-11
  - max trade_date: 2026-05-28
  - state rows: 6492
  - old rows before 2026-05-10: 0
  - checkpoint rows: 2
  - episode rows: 2064
  - performance rows: 2

## 6. Fresh smoke

- run_id: `hsmm_lifecycle_smoke_fresh_v2`
- verdict: `PartialLifecycleSignal`
- report path: `reports/hsmm_diagnostics/hsmm_lifecycle_smoke_fresh_v2`
- generated state rows: 7884
- generated checkpoint rows: 2
- generated episode rows: 2224
- performance file non-empty: yes

Fresh smoke command:

```bash
.venv/bin/python -m src.models.hsmm_walk_forward \
  --db data/db/a_share_hmm.duckdb \
  --start-date 2026-05-01 \
  --end-date 2026-05-28 \
  --n-states 4 \
  --max-duration 20 \
  --train-window-days 80 \
  --train-frequency every_n_trade_days \
  --train-every-n-trade-days 10 \
  --snapshot-frequency daily \
  --n-iter 2 \
  --run-id hsmm_lifecycle_smoke_fresh_v2
```

Diagnostics command:

```bash
.venv/bin/python -m src.evaluation.hsmm_diagnostics \
  --db data/db/a_share_hmm.duckdb \
  --run-id hsmm_lifecycle_smoke_fresh_v2 \
  --horizons 1,3,5,10 \
  --enable-exit-calibration \
  --output reports/hsmm_diagnostics/hsmm_lifecycle_smoke_fresh_v2
```

### 6.1 Causality

- causality audit: passed
- `state_source == causal_hsmm`: passed
- `train_end_date <= trade_date`: passed
- `checkpoint_train_end_date <= state_trade_date`: passed
- `max_observation_date_used <= trade_date`: passed
- `decode_mode == causal_prefix_viterbi`: passed
- `snapshot_frequency == daily`: passed

### 6.2 Coverage

| layer | expected sectors | actual sectors | expected rows | actual rows | coverage ratio | passed |
|---|---:|---:|---:|---:|---:|---|
| raw OHLCV universe | 466 | 466 | 7922 | 7918 | 0.999495 | true |
| feature eligible universe | 466 | 464 | 466 | 464 | 0.995708 | true |
| model decodable universe | 464 | 464 | 7884 | 7884 | 1.000000 | true |
| verdict coverage | 464 | 464 | 7884 | 7884 | 1.000000 | true |

Missing reasons:

| sector_id | layer | reason | details |
|---|---|---|---|
| concept:2026一季报预增 | feature_eligible | insufficient_history | raw_days=17, clean_rows=16 |
| concept:数据中心(AIDC) | feature_eligible | insufficient_history | raw_days=17, clean_rows=0 |

### 6.3 Age stability

- row count: 7884
- null `model_state_age_days`: 0
- null `label_state_age_days`: 0
- null `duration_model_age_days`: 0
- null `display_state_age_days`: 0
- same-label age decrease count: 0
- aggregate age stability passed: true

### 6.4 Episode censoring

- episode count: 2224
- left-censored episodes: 464
- right-censored episodes: 464
- `censored_episode_profile.csv`: generated
- duration profile excludes censored episodes: yes

### 6.5 Exit calibration

- `exit_calibration_summary.csv`: generated
- `exit_calibration_buckets.csv`: generated
- raw and calibrated probability rows are both present
- validation window: 2026-05-21 至 2026-05-27
- short smoke window means some state/horizon buckets are marked `insufficient_validation_sample`

Selected rows:

| horizon | state | prob type | sample count | brier score | calibration error | insufficient |
|---:|---|---|---:|---:|---:|---|
| 1 | Neutral | raw | 874 | 0.174436 | 0.102544 | false |
| 1 | Neutral | calibrated | 874 | 0.207711 | 0.171957 | false |
| 3 | Stress | raw | 530 | 0.162207 | 0.177431 | false |
| 3 | Stress | calibrated | 530 | 0.129059 | 0.083447 | false |
| 5 | Repair | calibrated | 4 | 0.023712 | 0.137910 | true |

### 6.6 Stress lifecycle

- `stress_lifecycle_profile.csv`: generated
- contains `predicted_next_state_distribution`: yes
- contains `realized_next_state_distribution`: yes
- realized transition distribution comes from actual episode next-state labels, not from predicted next-state labels.

Selected Stress rows:

| age bucket | sample count | actual exit 1d | actual exit 3d | actual exit 5d | insufficient |
|---|---:|---:|---:|---:|---|
| 1-3 | 896 | 0.143036 | 0.189565 | 0.302632 | false |
| 4-7 | 505 | 0.034211 | 0.063492 | 0.129032 | false |
| 8-14 | 86 | 0.033898 | 0.285714 | 0.375000 | false |
| 15+ | 3 | 0.000000 | NaN | NaN | true |

### 6.7 HMM vs HSMM comparison

- no `--hmm-cache-key` was provided
- comparison status: `skipped_no_matched_hmm_cache`
- all-HMM-cache mixing: not performed

## 7. Full primary

- run_id: `hsmm_lifecycle_primary_v1`
- status: not completed in this interactive run
- checkpoint rows after termination: 0
- state rows after termination: 0
- episode rows after termination: 0

Command attempted:

```bash
.venv/bin/python -m src.models.hsmm_walk_forward \
  --db data/db/a_share_hmm.duckdb \
  --start-date 2025-01-02 \
  --end-date 2026-05-28 \
  --n-states 4 \
  --max-duration 40 \
  --train-window-days 504 \
  --train-frequency monthly \
  --snapshot-frequency daily \
  --n-iter 10 \
  --run-id hsmm_lifecycle_primary_v1
```

Reason not completed:

- The full primary has 337 snapshot dates and 18 monthly checkpoints.
- It covers about 466 sector sequences.
- It uses `max_duration=40` and `n_iter=10`, much heavier than the smoke run.
- Before this patch, CLI progress output was absent and checkpoint rows were only written after all checkpoint training completed, so the command looked stalled for a long time.

Mitigation added in this package:

- `src/models/hsmm_walk_forward.py` now passes a CLI `progress_callback`.
- Long runs now print stage, current count, total count, and date, for example:

```text
[23:59:59] checkpoint_trained: 1/18 @ 2025-01-02
[00:00:10] snapshot_decoded: 1/337 @ 2025-01-02
```

Recommended next run:

- Re-run the same full primary command after this progress patch.
- Treat full primary as a long-running local validation job, not as an interactive smoke test.
- Consider a future engineering optimization to persist checkpoint/performance rows incrementally after each checkpoint.

## 8. Remaining failures

| failure | likely cause | proposed next action |
|---|---|---|
| Full primary not completed | Full primary is computationally heavy and earlier CLI had no progress output until completion | Re-run full primary with the new progress output; optionally add incremental checkpoint persistence |
| Short smoke verdict is only `PartialLifecycleSignal` | Smoke range is only May 2026 and insufficient for model-validity evidence | Use full primary diagnostics as the real lifecycle evidence |

## 9. Engineering changes included

- HSMM state daily fields now separate model age, label age, duration-model age, and display age.
- Raw and calibrated exit probabilities are separated.
- Episode censoring flags and reasons are persisted.
- Diagnostics coverage audit now outputs raw OHLCV, feature eligible, and model decodable layers.
- Stress lifecycle profile now separates predicted and realized next-state distributions.
- HMM vs HSMM comparison requires an explicit `--hmm-cache-key`; otherwise it skips with `skipped_no_matched_hmm_cache`.
- CLI HSMM walk-forward now prints progress via the existing progress callback.

