# STAGE00_WP_B_baseline_freeze

阶段：Stage 00 / 冻结现状与建立证据账本
工作包编号：WP-B
执行者：Codex 线程 B
并行边界：可与 WP-A、WP-C 并行；本包只冻结 V0 当前基线并生成 baseline validation snapshot，不改模型算法，不改 UI gate，不抓取新数据。

## 目标

阶段 0 需要先把当前版本固化为可验收 baseline。后续并行开发会快速改变仓库状态，如果没有 baseline freeze，就无法判断后续改动是否破坏当前 HMM/HSMM 能力边界。

本包需要生成人工可读和机器可读的基线快照，记录源码结构、依赖、Python/DuckDB/OS 环境、DuckDB 关键表行数与日期范围、run_id、feature scope、universe 信息、HMM 与 signal validation 当前结论、HSMM lifecycle 与 UI readiness 现状、测试命令与结果。若 WP-A registry 已存在则写入证据账本；否则生成 evidence_seed.jsonl。

## 禁止事项

1. 不训练新的 HMM/HSMM 主模型，除非只是 smoke test 且不会覆盖 primary run。
2. 不抓取行情数据，不更新成分股，不调用 AKShare/Tencent。
3. 不修改 UI readiness 逻辑；只审计和报告。
4. 不把当前 HMM/HSMM 输出升级为 validated_signal 或 decision_support。
5. 不用样本内状态替代 causal walk-forward。
6. 不删除旧报告；如需清理，只列出候选文件，不实际删除。

## 建议修改范围

优先新增：

```text
src/evaluation/baseline_freeze.py
src/evaluation/baseline_collectors.py
tests/test_baseline_freeze.py
```

允许读取但尽量不修改：

```text
src/data_pipeline/storage.py
src/evaluation/signal_validation.py
src/evaluation/hsmm_display_lifecycle.py
src/evaluation/hsmm_lifecycle_probability_report.py
src/ui/lifecycle_page.py
```

## 输出目录

默认输出：

```text
reports/baseline_freeze/stage00_v0_baseline_20260601/
  summary.md
  baseline_snapshot.json
  db_table_profile.csv
  run_inventory.csv
  validation_commands.json
  evidence_seed.jsonl
  missing_artifacts.md
```

如果本地数据库不存在，仍需生成 `summary.md`、`baseline_snapshot.json`、`missing_artifacts.md`，并明确 `db_available=false`。

## CLI 要求

新增 CLI：

```bash
python -m src.evaluation.baseline_freeze \
  --db data/db/a_share_hmm.duckdb \
  --output reports/baseline_freeze/stage00_v0_baseline_20260601 \
  --run-tests no \
  --no-fetch
```

必须支持参数：

```text
--db
--output
--run-tests {no,unit,not-slow,all}
--no-fetch
--strict
--register-evidence
```

语义：

- `--no-fetch` 为默认行为，禁止任何外部数据更新。
- `--run-tests no` 只收集已有信息。
- `--run-tests unit` 运行本包或轻量测试。
- `--run-tests not-slow` 运行 `pytest -q -m "not slow"`。
- `--register-evidence` 在 WP-A registry 可用时写入 evidence，否则生成 `evidence_seed.jsonl`。
- `--strict` 在关键 artifact 缺失时返回非 0，默认只记录 warning。

## 必须收集的内容

### 环境

记录：

```text
python_version
duckdb_version
platform
working_directory
is_git_repo
git_sha or unknown
requirements hash or package list
created_at
```

### 数据库关键表 inventory

至少检查：

```text
model_runs
sector_state_daily
walk_forward_cache_runs
walk_forward_state_cache
hsmm_model_runs
hsmm_model_checkpoints
hsmm_state_daily
hsmm_state_episodes
hsmm_display_label_episodes
hsmm_lifecycle_ui_daily
hsmm_lifecycle_duration_profile
hsmm_next_state_tendency_profile
market_breadth_daily
sector_features
```

对每张存在的表输出：

```text
table_name
row_count
min_trade_date
max_trade_date
distinct_run_count
distinct_sector_count
feature_scope_id sample
universe_id sample
```

缺字段时写 null 与说明，不得默认通过。

### V0 基线事实核对

如 DB 和报告存在，summary 至少核对：

```text
HSMM run_id=hsmm_lifecycle_primary_v1
full_run lifecycle rows 参考值约 155118
数据范围参考 2025-01-02 至 2026-05-28
sector_count 参考 464
trade_day_count 参考 337
lifecycle_ui_daily duplicate sector-date keys 参考 0
cutoff_only as-of report max trade_date <= cutoff date
future episode leakage count 参考 0
invalid/missing/insufficient raw_score_used violations 参考 0
```

这些数字是 V0 参考点，不是硬编码通过条件。实际 DB 不一致时输出 diff，不覆盖数据。

### HMM / signal validation 当前边界

必须查找并记录：

```text
reports/signal_validation/primary_20260529_main/summary.md
OVERALL_EVALUATION_20260530.md
EVALUATION_README.md
```

缺失则写入 `missing_artifacts.md`。

summary 中必须明确：HMM 当前定位是 causal nowcast / state context / weak auxiliary signal；不接受为 standalone trading decision engine；默认 evidence_level 为 internal_diagnostic 或 research_only，不是 validated_signal。

### HSMM lifecycle 当前边界

必须查找并记录：

```text
HSMM_LIFECYCLE_UI_V0_HARDENING_TEST_RESULTS_20260601.md
HSMM_DISPLAY_LIFECYCLE_EVALUATION_20260601.md
HSMM_PROBABILITY_VALIDITY_EVALUATION_20260531.md
reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof_full_run
reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof_20251031_cutoff_only
```

summary 中必须明确：state age 可展示；state phase 可展示；低/中/高 exit tendency 仅内部诊断；numeric p_exit 隐藏，除非 usable_probability/readiness 通过；next-state tendency 是 realized-profile tendency，不是预测概率；HSMM 不用于排序或交易推荐。

## 测试要求

新增测试至少覆盖：

1. 无 DB 时 CLI 仍生成 summary 和 JSON，且 `db_available=false`。
2. 临时 DuckDB 缺少部分表时不崩溃。
3. 表存在时能统计 row count/date range。
4. `--no-fetch` 默认启用，且不得调用 updater/akshare client。
5. registry 不存在时生成 `evidence_seed.jsonl`。
6. JSON 可 `json.load`，CSV 可 pandas 读取。

建议命令：

```bash
python -m compileall -q src tests
pytest -q tests/test_baseline_freeze.py
pytest -q -m "not slow"
```

本地数据可用时额外运行：

```bash
python -m src.evaluation.baseline_freeze \
  --db data/db/a_share_hmm.duckdb \
  --output reports/baseline_freeze/stage00_v0_baseline_20260601 \
  --run-tests no \
  --no-fetch \
  --register-evidence
```

## 本地数据需求

使用 V0 当前本地 DB：

```text
data/db/a_share_hmm.duckdb
```

不得抓取新数据。DB 缺失时输出缺失状态，不自动下载或更新。

summary 中必须附：

```text
DB found
DB path
DB file size
DuckDB opened read-only
External fetch attempted=no
```

## 交付物

Codex 完成后必须提交：

```text
src/evaluation/baseline_freeze.py
src/evaluation/baseline_collectors.py        # 如拆分实现
tests/test_baseline_freeze.py
reports/baseline_freeze/stage00_v0_baseline_20260601/summary.md
reports/baseline_freeze/stage00_v0_baseline_20260601/baseline_snapshot.json
reports/baseline_freeze/stage00_v0_baseline_20260601/db_table_profile.csv
reports/baseline_freeze/stage00_v0_baseline_20260601/run_inventory.csv
reports/baseline_freeze/stage00_v0_baseline_20260601/evidence_seed.jsonl
reports/baseline_freeze/stage00_v0_baseline_20260601/missing_artifacts.md
```

## 验收标准

本包通过标准：

1. baseline snapshot 可重复生成。
2. JSON/CSV/MD 完整可读。
3. 明确列出 HMM/HSMM 能力边界。
4. 明确区分 sample-in 与 causal walk-forward。
5. 明确 readiness 限制，尤其 HSMM 数值 `p_exit` 不可泛化展示。
6. 没有抓取新数据。
7. 新增测试通过。
8. 若 WP-A 已合并，能注册至少一条 `baseline_freeze` validation run；若未合并，能生成 `evidence_seed.jsonl`。

## 失败降级

如果本地 DB 无法打开：

```text
写 db_open_error；从现有 Markdown 报告抽取可用基线；summary verdict 设为 BaselineFreezePartialDueToDbUnavailable；不下载数据，不重建数据库。
```

如果 report 缺失：

```text
在 missing_artifacts.md 列出路径；不编造结果；summary 对应模块标记 missing_evidence。
```

## Codex 回传格式

请按以下格式回传：

```text
WP: STAGE00_WP_B_baseline_freeze
状态: pass / partial / fail
修改文件:
- ...
运行命令与结果:
- command: ...
  result: ...
生成报告:
- ...
本地数据使用情况:
- DB found: yes/no
- 是否抓取新数据: no
当前 baseline verdict:
- HMM: ...
- HSMM lifecycle: ...
- UI readiness: ...
风险与遗留问题:
- ...
需要我验收的重点:
- ...
```
