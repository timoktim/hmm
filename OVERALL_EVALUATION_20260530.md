# A股板块 HMM 分析器整体评估说明 2026-05-30

## 1. 本包用途

本评估包用于整体代码审阅、功能验收和二次开发评估。包内包含源码、测试、运行脚本、说明文档和已生成的信号有效性报告；不包含本机数据库、缓存、模型产物、虚拟环境和旧 zip 包。

建议评估入口：

1. `README.md`
2. `EVALUATION_README.md`
3. `CHATGPT_PROGRAM_GUIDE.md`
4. `COMPLETION_AUDIT_20260529.md`
5. `HSMM_P0_COMPLETION_20260530.md`
6. `reports/signal_validation/primary_20260529_main/summary.md`
7. `reports/hsmm_diagnostics/hsmm_lifecycle_p0_smoke_20260530/summary.md`

## 2. 当前系统定位

本项目是本地投研辅助工具，不是自动交易系统。

核心模块：

- 数据中心：管理行业、概念、成分股、个股行情、全 A 宽度链路、大盘指数和市场基准。
- Universe Manager：组合行业板块、概念板块和自定义股票池。
- 大盘 HMM：识别整体市场环境，只作为风险提示。
- 板块 HMM：识别板块当前状态，定位为 nowcast，不应直接解释为收益预测。
- HSMM 生命周期模型：旁路模型，用于状态年龄、状态阶段、退出概率和下一状态诊断。
- 模型评估 / 信号验证：检查状态后收益、IC、策略对照、随机基线和成本敏感性。
- Stock Filter：在板块或股票池内做透明筛选，不提供买卖指令。

## 3. 最近一次信号有效性判断

报告路径：

```text
reports/signal_validation/primary_20260529_main/summary.md
```

主结论：`Weak`。

关键信息：

- 因果审计通过：`state_source == causal_backtest`、`train_end <= trade_date`、`max_observation_date_used <= trade_date`、`exec_date > signal_date`。
- 数据覆盖：2025-01-02 至 2026-05-28，465 个板块，68 个有效信号日，30,937 条状态样本。
- 状态区分度：TrendUp 在部分中短期 horizon 上相对 Neutral / RiskOff 有正 spread。
- 排序能力：`score_prob_spread` 在 5/10/20 日有弱正 IC，但统计强度不足。
- 策略对照：默认 0.1% 单边成本后，HMM 策略未能优于 RS20，也明显弱于全板块等权。
- 随机基线：200 次随机 Top-N 对照不支持 HMM 策略具备强有效性。

评估含义：

当前 HMM 更适合作为“状态识别 / nowcast”工具，而不是单独交易策略。下一步重点应放在状态生命周期诊断、数据质量和信号解释，而不是继续堆叠交易规则。

## 4. HSMM 生命周期模型完成情况

已完成：

- `src/models/hsmm_model.py`
  - `DiscreteDurationGaussianHSMM`
  - semi-Markov Viterbi segmentation
  - Viterbi-EM / hard EM
  - 显式 duration PMF
  - 对角 Gaussian emission
  - `state_age_days`
  - `duration_percentile`
  - `state_phase`
  - `p_exit_1d/3d/5d/10d`
  - `expected_remaining_days`
  - `most_likely_next_state`

- `src/features/hsmm_features.py`
  - 多周期绝对收益、相对收益、波动、回撤、均线斜率和成交额热度。
  - 不包含 forward/future return。

- `src/models/hsmm_walk_forward.py`
  - checkpoint 训练 + daily snapshot。
  - 因果 prefix Viterbi 解码。
  - `state_source = causal_hsmm`。
  - 写入 `hsmm_state_daily`、`hsmm_state_episodes`、`hsmm_model_runs`、`hsmm_model_checkpoints`、`hsmm_parameters`。

- `src/evaluation/hsmm_diagnostics.py`
  - 因果性审计。
  - snapshot frequency audit。
  - 状态画像。
  - 持续时间画像。
  - 按交易日 horizon 计算退出概率校准。
  - 下一状态预测。
  - 状态阶段画像。
  - Stress lifecycle profile。
  - churn profile。
  - P0 verdict。

真实数据 P0 smoke run：

```text
run_id: hsmm_lifecycle_p0_smoke_20260530
reports/hsmm_diagnostics/hsmm_lifecycle_p0_smoke_20260530/summary.md
```

结果：

- 因果审计：通过
- daily snapshot：通过
- checkpoint 可追溯：通过
- 状态行：7884
- 交易日：17
- 板块数：464
- verdict：`InvalidDueToCalibrationFailure`

解释：

HSMM P0 的工程口径已修正，但真实数据 smoke run 显示退出概率校准缺少基本单调性。因此当前不建议进入 HSMM UI 展示或策略解释阶段。

未完成但按工程文档暂不属于本阶段：

- HSMM UI 只读展示页。
- 完整 forward-backward posterior。
- 将 HSMM 接入收益预测或交易排序。
- market-regime-conditioned HSMM。

## 5. 关键边界与防误读

- HMM 后验概率不是上涨概率。
- HSMM 的 `p_exit` 是退出当前状态概率，不是下跌概率，也不是上涨概率。
- `RiskOff` 命名仍需谨慎；HSMM 默认标签使用 Trend / Neutral / Stress / Repair 等更中性语义。
- 市场宽度只有在 `breadth_mode = full_market` 且覆盖率达标时，才可解释为全 A 宽度。
- 回测必须使用因果 walk-forward 状态，不能使用样本内状态展示结果。
- 本包不含本地 DuckDB 数据库，复现真实结果需要重新抓取或接入已有数据库。

## 6. 测试结果

最近一次验证：

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

## 7. 推荐审阅重点

建议重点检查：

- HSMM Viterbi 是否严格 semi-Markov，没有把普通 HMM Viterbi 当 HSMM。
- 多 sector 训练是否没有跨 sector 转移泄露。
- `hsmm_state_daily` 是否满足 `train_end_date <= trade_date` 和 `max_observation_date_used <= trade_date`。
- HSMM 特征是否不含 future/forward return。
- 信号有效性报告是否将策略结论降级为 Weak，避免过度宣传。
- 数据中心覆盖率和市场宽度口径是否仍然清晰。

## 8. 下一轮建议

建议优先级：

1. 优先修 HSMM duration calibration，而不是做 UI。
2. 检查 duration PMF、状态标签稳定性、训练频率和特征是否导致 `p_exit` 校准失效。
3. 只有当 diagnostics verdict 至少达到 `PartialLifecycleSignal`，再考虑 HSMM Lifecycle 只读 UI。
4. 继续优化信号验证性能，让参数网格鲁棒性检查可在合理时间内完成。
5. 不要把 HSMM 接入交易排序，先证明生命周期预测有增量价值。
