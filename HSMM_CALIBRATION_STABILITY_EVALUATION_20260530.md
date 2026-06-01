# HSMM Lifecycle Calibration and Stability Evaluation

版本日期：2026-05-30

本评估说明对应 `codex_hsmm_lifecycle_calibration_stability_package.md` 工作包。本轮没有接入 UI，也没有把 HSMM 用作交易排序；重点是让 HSMM 生命周期诊断具备可复现、可审计、可校准的工程基础。

## 关键改动

1. 同 `run_id` 重跑默认清理旧结果，避免旧状态、旧 episode、旧 checkpoint 污染诊断。
2. `coverage_snapshot` 改为基于 run 对应的真实 OHLCV scope 计算 expected universe 和 expected trade dates，不再从已生成 states 反推覆盖率。
3. `causality_audit` 增强 checkpoint 追溯、重复状态键、episode 边界、状态日期范围等检查。
4. `state_age_days_by_label` 在输出层跨 checkpoint 缝合，避免同 label 连续但年龄无故重置。
5. 新增 `hsmm_run_performance` 表，记录 checkpoint 训练和解码耗时。
6. 新增 `src/evaluation/hsmm_exit_calibration.py`，区分 raw exit probability 与 calibrated exit probability。
7. diagnostics 新增时间切分校准输出：
   - `exit_probability_calibrated.csv`
   - `calibration_train_valid_split.csv`
   - `calibrator_metadata.json`
8. verdict 规则改为分层短路：
   - causality failure
   - coverage failure
   - insufficient sample
   - age instability
   - calibration failure
   - no lifecycle increment
   - partial / valid lifecycle signal

## 已生成诊断报告

最新诊断报告目录：

```text
reports/hsmm_diagnostics/hsmm_lifecycle_p0_smoke_20260530_calibration_v2
```

当前结论：

```text
InvalidDueToCoverageFailure
```

含义：

因果审计通过，但覆盖审计发现该 smoke run 的真实输入范围应覆盖 466 个板块，实际状态覆盖 464 个板块，状态行 `7884 / 7922`，覆盖率约 `99.52%`。这不是模型有效性失败，而是更严格的 coverage audit 正确暴露了 run 输出不完整的问题。完整 primary run 之前不应把该 smoke run 解释为有效生命周期证据。

## 验证命令

本轮已验证：

```bash
python -m pytest -q
python -m pytest -q -m "not slow"
python -m pytest -q -m slow
python -m compileall -q src tests
```

结果：

```text
python -m pytest -q                  -> 135 passed, 2 skipped
python -m pytest -q -m "not slow"    -> 135 passed, 2 deselected
python -m pytest -q -m slow          -> 2 passed, 135 deselected
python -m compileall -q src tests    -> passed
```

## 受影响模块

```text
src/models/hsmm_walk_forward.py
src/evaluation/hsmm_diagnostics.py
src/evaluation/hsmm_exit_calibration.py
src/data_pipeline/storage.py
tests/test_hsmm_calibration_stability.py
tests/test_hsmm_diagnostics.py
tests/test_hsmm_storage.py
tests/test_hsmm_walk_forward.py
```

## 尚未执行的重任务

完整 primary run 尚未在本轮交互中执行：

```bash
python -m src.models.hsmm_walk_forward \
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

原因：

当前数据库中该区间约有 337 个交易日、466 个板块、15.6 万行板块行情。按 primary 配置运行成本较高，适合作为单独离线任务执行。现在 `hsmm_run_performance` 已经落库，后续 primary run 可定位训练或解码耗时瓶颈。

## 下一轮建议

1. 单独运行 `hsmm_lifecycle_primary_v1`，不要改参数挑结果。
2. 若 primary run 仍为 coverage failure，先定位缺失板块是否来自短历史、缺行情或特征窗口不足。
3. 若覆盖和因果均通过，再看 raw/calibrated exit calibration、next-state prediction、HMM vs HSMM churn。
4. 未达到 `PartialLifecycleSignal` 前，不接 UI、不做交易排序。
