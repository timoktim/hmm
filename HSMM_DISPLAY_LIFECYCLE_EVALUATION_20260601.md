# HSMM 状态生命周期 Stage1/Stage2 评估说明

本评估说明对应 `codex_lifecycle_stage1_stage2_work_package.md` 工作包。本轮将 HSMM 产品层收敛为“状态生命周期分析器”，只展示状态、状态年龄、生命周期阶段和低/中/高退出倾向；不展示未经验证的精确概率，不输出交易信号。

## 本轮新增内容

- `src/evaluation/hsmm_display_lifecycle.py`
  - 从 `hsmm_state_daily` 构造用户可见的 display-label episode。
  - 计算 display-label 历史持续时间分布。
  - 生成 early / mature / late 状态阶段。
  - 生成 `low / medium / high / unavailable` 退出倾向。
  - 生成 realized next-state tendency。
  - 输出并落库 `hsmm_lifecycle_ui_daily`。

- 新增表：
  - `hsmm_display_label_episodes`
  - `hsmm_lifecycle_ui_daily`

- 新增测试：
  - `tests/test_hsmm_display_lifecycle.py`
  - `tests/test_hsmm_lifecycle_ui_integration.py`

## 主报告位置

```text
reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1/
```

重点文件：

```text
summary.md
display_label_episodes.csv
display_duration_profile.csv
exit_tendency_profile.csv
next_state_tendency_profile.csv
lifecycle_ui_daily.csv
ui_field_policy.csv
config.json
```

## primary run 结果

```text
run_id: hsmm_lifecycle_primary_v1
Conclusion: LifecycleStageAndTendencyReadyForInternalUI
state_rows: 155118
display_label_episode_count: 29199
lifecycle_ui_daily_rows: 155118
duplicate_sector_date_keys: False
```

## display-label duration profile

```text
Neutral median duration: 3 trading days
Repair  median duration: 4 trading days
Stress  median duration: 3 trading days
Trend   median duration: 4 trading days
```

## state phase distribution

```text
early: 50814
mature: 52935
late: 51369
```

## UI 展示策略

正式 UI 主路径只应读取：

```text
hsmm_lifecycle_ui_daily
```

允许展示：

```text
state_label
display_state_age_days
state_phase
historical_median_duration_days
duration_percentile_display
exit_tendency_1d / 3d / 5d / 10d / 20d
next_state_tendency
```

禁止展示：

```text
raw_p_exit_* 百分比
calibrated_p_exit_* 百分比
next_state_probability
上涨概率
买入 / 卖出 / 推荐
未来收益率预测
```

## 测试结果

最近验证：

```text
python -m pytest -q: 168 passed, 2 skipped
python -m pytest -q -m "not slow": 168 passed, 2 deselected
python -m pytest -q -m slow: 2 passed, 168 deselected
```

## 结论

本轮满足 Internal UI 接入标准。下一步可以在板块详情或单独“生命周期”视图中接入 `hsmm_lifecycle_ui_daily`，但仍不得把未经验证的 `p_exit` 展示成概率。

