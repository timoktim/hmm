# HSMM 生命周期 P0 完成记录 2026-05-30

工作包：`HSMM-LIFECYCLE-P0-20260530`

## 完成内容

本轮把 HSMM 从“可运行骨架”修成了“可审计的生命周期诊断器”：

- `hsmm_model_runs` 增加 `train_frequency`、`snapshot_frequency`、`config_hash`、`run_hash`、`include_custom_baskets`。
- 新增 `hsmm_model_checkpoints`，每次训练 checkpoint 可追溯。
- `hsmm_state_daily` 增加 `checkpoint_id`、`decode_mode`、`snapshot_frequency`、`state_age_days_by_id`、`state_age_days_by_label`。
- `hsmm_state_episodes` 增加 `episode_id`、`duration_trading_days`、`duration_calendar_days`、`checkpoint_id_start/end`、`is_open_episode`。
- `p_exit_h` 修正为交易日生命周期语义：`D == age` 计入 `p_exit_1d`。
- walk-forward 拆分为 checkpoint 训练与 daily snapshot 输出。
- 每个 snapshot 使用 `causal_prefix_viterbi`，只读取 `trade_date <= t` 的观测。
- diagnostics 的 horizon 全部改为未来 N 个交易行，不再使用自然日 `Timedelta`。
- diagnostics 按 run 的 `universe_id` / `include_custom_baskets` 读取数据。
- diagnostics 输出 P0 verdict：`ValidLifecycleSignal`、`PartialLifecycleSignal`、`WeakLifecycleSignal`、`InvalidDueToCausalLeakage`、`InvalidDueToSparseSnapshots`、`InvalidDueToCalibrationFailure`。

## 真实数据 smoke run

命令：

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
  --run-id hsmm_lifecycle_p0_smoke_20260530
```

结果：

- checkpoint_rows: 2
- state_rows: 7884
- episode_rows: 2224
- 状态日期：2026-05-06 至 2026-05-28
- 交易日数：17
- 板块数：464

诊断报告：

```text
reports/hsmm_diagnostics/hsmm_lifecycle_p0_smoke_20260530/summary.md
```

诊断 verdict：

```text
InvalidDueToCalibrationFailure
```

原因：因果审计和 daily snapshot 审计均通过，但退出概率校准缺少基本单调性。按工作包要求，不能把该结果包装成正向生命周期信号。

## 是否满足 UI 接入条件

暂不满足。

理由：

- 因果性通过。
- daily snapshot 口径通过。
- checkpoint 可追溯通过。
- 但 `p_exit` calibration 未通过，且 next-state prediction 多数状态未优于 baseline。

下一步应先改进 duration PMF、状态标签稳定性、训练频率或特征，而不是做 UI 展示。

## 测试结果

```bash
.venv/bin/python -m pytest -q tests/test_hsmm_model.py tests/test_hsmm_storage.py tests/test_hsmm_walk_forward.py tests/test_hsmm_diagnostics.py
# 10 passed

.venv/bin/python -m pytest -q -m "not slow"
# 125 passed, 2 deselected

.venv/bin/python -m pytest -q -m slow
# 2 passed, 125 deselected

.venv/bin/python -m compileall -q src tests
# passed
```

## 关键文件

- `src/models/hsmm_model.py`
- `src/models/hsmm_walk_forward.py`
- `src/evaluation/hsmm_diagnostics.py`
- `src/data_pipeline/storage.py`
- `tests/test_hsmm_model.py`
- `tests/test_hsmm_walk_forward.py`
- `tests/test_hsmm_diagnostics.py`
- `tests/test_hsmm_storage.py`
