# HSMM 生命周期概率有效性评估说明

本评估说明对应 `codex_hsmm_lifecycle_probability_validity_work_package.md` 工作包。本轮没有把 HSMM 生命周期概率接入正式 UI，也没有用于交易排序；重点是验证这些概率是否有可解释、可校准、可降级的展示语义。

## 本轮新增评估模块

- `src/evaluation/hsmm_exit_targets.py`
  - 生成 `state_id_exit` 与 `display_label_exit` 两套退出目标。
  - horizon 使用未来交易行数，不使用自然日。
- `src/evaluation/hsmm_lifecycle_calibration.py`
  - 按 `state_label + horizon + exit_type` 验证 raw、empirical shrinkage、logistic、isotonic。
  - 输出 `usable_probability`、`raw_only`、`ordinal_only`、`insufficient_sample`、`invalid`。
- `src/evaluation/hsmm_transition_validation.py`
  - 验证下一状态预测是否优于 global / age-bucket baseline。
- `src/evaluation/hsmm_lifecycle_probability_report.py`
  - 生成分层 verdict、UI readiness matrix 和完整报告文件。

## 主报告位置

报告目录：

```text
reports/hsmm_lifecycle_probability/hsmm_lifecycle_primary_v1/
```

重点文件：

```text
summary.md
config.json
ui_readiness_matrix.csv
selected_exit_probability_status.csv
selected_exit_probability_daily.csv
transition_validation_summary.csv
transition_validation_by_age_bucket.csv
duration_profile_by_state_id.csv
duration_profile_by_display_label.csv
duration_hidden_vs_display.csv
duration_profile_hidden_vs_label.csv
known_limitations.md
```

## primary run 结论

```text
run_id: hsmm_lifecycle_primary_v1
overall_verdict: PartialLifecycleProbability
engineering_verdict: EngineeringPass
calibration_verdict: PartialLifecycleProbability
transition_verdict: TransitionModelUseful
stress_lifecycle_verdict: StressLifecycleMixed
display_readiness_verdict: DisplayAllowedProbability
```

## 概率展示结论

共评估 40 个 `state_label + horizon + exit_type` 切片：

```text
usable_probability: 4
raw_only: 8
ordinal_only: 21
invalid: 7
```

可以作为数值概率展示的切片只有：

```text
display_label / Stress / 10d / logistic
display_label / Trend / 1d / isotonic
state_id / Neutral / 10d / empirical_shrinkage
state_id / Stress / 10d / logistic
```

必须隐藏的切片：

```text
display_label / Repair / 10d
display_label / Repair / 20d
display_label / Stress / 3d
state_id / Neutral / 3d
state_id / Repair / 10d
state_id / Repair / 20d
state_id / Stress / 3d
```

其余切片只能作为高/中/低退出压力或内部排序诊断，不应显示为百分比概率。

## 下一状态预测结论

```text
Neutral: empirical_baseline_only
Repair: empirical_baseline_only
Stress: usable_model_prediction
Trend: hidden
```

这意味着下一状态预测不能整体展示为模型概率；只能按状态局部启用，且需要读取 `transition_validation_summary.csv` 的状态。

## 测试结果

已验证：

```bash
python -m pytest -q
python -m pytest -q -m "not slow"
python -m pytest -q -m slow
```

最近结果：

```text
python -m pytest -q: 157 passed, 2 skipped
python -m pytest -q -m "not slow": 157 passed, 2 deselected
python -m pytest -q -m slow: 2 passed, 157 deselected
```

## 使用建议

本轮结果支持进入“内部研究/诊断展示”阶段，但不建议把所有 HSMM `p_exit` 字段直接做成正式 UI 百分比。正式展示必须先读取 `ui_readiness_matrix.csv`：

- `can_show_numeric_probability = true`：允许显示数值概率。
- `can_show_ordinal_score = true`：只允许显示高/中/低压力。
- `must_hide = true`：正式 UI 必须隐藏。

