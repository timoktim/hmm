# HSMM Lifecycle UI v0 Local Test Results

生成日期：2026-06-01  
代码版本：not available（当前目录不是 git repository）  
数据库路径：`data/db/a_share_hmm.duckdb`  
Python：3.12.13  
DuckDB：1.5.3  
OS：macOS-26.4.1-arm64  
CPU：Apple M3 Pro，12 cores  
内存：18 GB  
venv：`.venv`  
数据范围：2025-01-02 至 2026-05-28  
sector_count：464  
trade_day_count：337  

## 1. Test Summary

- compileall：PASS，`.venv/bin/python -m compileall -q src tests`
- pytest -q：PASS，182 passed, 2 skipped, 25 warnings in 25.83s
- pytest -q -m "not slow"：PASS，182 passed, 2 deselected, 25 warnings in 25.28s
- pytest -q -m slow：PASS，2 passed, 182 deselected in 3.09s
- hsmm wildcard tests：PASS，65 passed in 10.17s
- lifecycle focused tests：PASS，24 passed in 0.96s
- failed tests：0
- skipped tests：2
- warnings：25，来自 synthetic signal validation 的 constant/NaN correlation warning，不影响生命周期 UI v0 契约。

## 2. Schema Migration

- passed：yes
- idempotent：yes，`DuckDBStorage.init_schema()` 连续执行 2 次通过
- missing tables：none
- required tables：
  - `hsmm_display_label_episodes`
  - `hsmm_lifecycle_ui_daily`
  - `hsmm_lifecycle_profile_metadata`
  - `hsmm_next_state_tendency_profile`
- required fields：passed，包括 `profile_mode`, `profile_cutoff_date`, `display_episode_id`, `raw_score_used_10d`, `next_state_tendency_phase_aware`, `source_probability_run_id`

## 3. Lifecycle latest_asof Run

- command：

```bash
.venv/bin/python -m src.evaluation.hsmm_display_lifecycle \
  --db data/db/a_share_hmm.duckdb \
  --run-id hsmm_lifecycle_primary_v1 \
  --profile-mode latest_asof \
  --profile-cutoff-date 2026-05-28 \
  --horizons 1,3,5,10,20 \
  --probability-report reports/hsmm_lifecycle_probability/hsmm_lifecycle_primary_v1 \
  --output reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof
```

- output path：`reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof`
- state row_count：155118
- lifecycle UI row_count：155118
- duplicate sector-date keys：0
- profile_mode：latest_asof
- profile_cutoff_date：2026-05-28
- profile_sample_window：2025-01-03 至 2026-05-27
- profile_completed_episode_count：28271
- conclusion：row count 对齐，主键无重复，关键字段空值为 0。

## 4. Display Episode Audit

- episode_count：29199
- left_censored：464
- right_censored：464
- open_episode_count：464
- same-label checkpoint reset count：0
- same-label age decrease count：0
- hidden-state change same-label cases：单元测试覆盖，display-label episode 不被 state_id 改变切断
- passed：yes

## 5. Exit Tendency Policy Audit

- invalid/missing raw_score_used violations：0
- policy audit rows：20
- allowed raw use：`usable_probability`, `raw_only`, `ordinal_only`
- blocked raw use：`invalid`, `insufficient_sample`, `missing`, `unknown`, `unverified`
- 5d distribution：
  - Neutral：high 14684 / medium 18999 / low 15205
  - Repair：high 20967 / medium 27407 / low 20882
  - Stress：high 5014 / medium 6515 / low 4958
  - Trend：high 6436 / medium 7899 / low 6152
- 10d distribution：
  - Neutral：high 14683 / medium 19511 / low 14694
  - Repair：high 22413 / medium 21590 / low 25253
  - Stress：high 5028 / medium 6484 / low 4975
  - Trend：high 6148 / medium 8188 / low 6151
- 20d saturation warning：not triggered in this run; 20d remains `detail_or_hide` per UI field policy
- passed：yes

## 6. As-of No-Lookahead Audit

- cutoff date：2025-10-31
- command output：`reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof_20251031`
- completed episodes used：15710
- max episode_end_date used：2025-10-30
- future episode leakage count：0
- latest cutoff 2026-05-28 max episode_end_date：2026-05-27
- passed：yes

## 7. Next-State Tendency Audit

- by_label output：yes，4 rows
- by_phase output：yes，12 rows
- by_age_bucket output：yes，16 rows
- low sample gating passed：yes，unit test covered `sample_count < min_next_state_sample => insufficient_sample`
- mixed gating passed：yes，Trend by-label top share 0.434224 is marked `Mixed`
- uses realized next label：yes，built from `hsmm_display_label_episodes.next_state_label`; no predicted next-state fields are read
- by-label summary：
  - Neutral → Repair, sample 11037, share 0.742140, usable
  - Repair → Neutral, sample 10400, share 0.826731, usable
  - Stress → Neutral, sample 2942, share 0.549286, usable
  - Trend → Mixed, sample 3892, top label Repair, share 0.434224
- passed：yes

## 8. UI Field and Text Policy

- lifecycle page import：PASS
- lifecycle page path：`src/ui/lifecycle_page.py`
- raw/calibrated p_exit visible：no
- lifecycle page direct raw/calibrated/strategy/backtest references：none
- forbidden text matches in lifecycle page：0
- `ui_text_policy_audit.csv` rows：20 legacy warnings outside lifecycle page, 0 errors
- `ui_field_policy.csv` rows：11
- required policy fields：present
  - `state_label: show`
  - `display_state_age_days: show`
  - `state_phase: show`
  - `exit_tendency_5d: show`
  - `exit_tendency_10d: show`
  - `exit_tendency_20d: detail_or_hide`
  - `raw_p_exit_*: hide`
  - `calibrated_p_exit_*: hide`
  - `next_state_probability: hide`
  - `next_state_tendency_phase_aware: show_if_status_usable_else_mixed`
- passed：yes

## 9. Optional HMM vs HSMM

- hmm_cache_key：skipped_no_matched_hmm_cache
- comparison_status：skipped
- key findings：not applicable

## 10. Artifacts

- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/summary.md`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/lifecycle_ui_daily_head100.csv`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/exit_tendency_policy_audit.csv`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/exit_tendency_distribution.csv`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/next_state_tendency_by_phase.csv`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/ui_field_policy.csv`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/ui_text_policy_audit.csv`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof/profile_metadata.json`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_retrospective/summary.md`
- `reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof_20251031/summary.md`

## 11. Remaining Issues

- 生命周期报告生成单次约数十秒，主要耗时在 155118 行状态 × 多 horizon 的 target/profile 构建和写入。功能正确，但后续可做增量化或缓存优化。
- 当前 `ui_text_policy_audit.csv` 对非生命周期旧页面仅标为 legacy warning；本工作包只要求生命周期页面不泄露交易化表达。

## Final Verdict

`PassForInternalLifecycleUI`
