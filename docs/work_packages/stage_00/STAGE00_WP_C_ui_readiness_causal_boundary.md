# STAGE00_WP_C_ui_readiness_causal_boundary

阶段：Stage 00 / 冻结现状与建立证据账本
工作包编号：WP-C
执行者：Codex 线程 C
并行边界：可与 WP-A、WP-B 并行；本包只做 UI readiness gate、样本内/因果边界和概率展示限制，不改模型训练，不重算 baseline，不抓取新数据。

## 目标

当前系统的主要误导风险不是模型不能运行，而是 UI 或报告把不同证据等级的输出放在同一视觉层级，或者让用户把 HMM posterior、HSMM `p_exit`、next-state tendency 误读成可直接实践判断的概率。

本包需要建立阶段 0 的 UI readiness gate 和 causal boundary：

1. UI 不得混合样本内状态和 causal walk-forward 状态。
2. 没有 causal cache 的策略评估只能显示为样本内解释或 research only。
3. HMM posterior 只能作为状态置信度或状态不清晰提示。
4. HSMM 数值 `p_exit` 不得绕过 readiness gate。
5. HSMM lifecycle 可显示状态年龄、阶段、低/中/高退出倾向，但必须标明内部诊断语义。
6. 核心 UI 输出需要带 `evidence_level`、`readiness_status`、`state_source` 或等价字段。

## 禁止事项

1. 不修改 HMM/HSMM 训练算法。
2. 不改 registry schema；schema 由 WP-A 负责。本包可以读取 policy 表，表不存在时使用内置保守策略。
3. 不生成新交易信号，不新增排序逻辑。
4. 不抓取新数据。
5. 不展示 raw/calibrated numeric p_exit，除非字段有 usable_probability 且 policy 允许。
6. 不把 realized next-state tendency 表述为模型预测概率。
7. 不大规模重构 UI，只做必要 gating、metadata 与文案修正。

## 建议修改范围

优先新增：

```text
src/ui/readiness_policy.py
src/ui/causal_boundary.py
src/ui/evidence_badges.py
tests/test_ui_readiness_policy.py
tests/test_ui_causal_boundary.py
```

可能小范围修改：

```text
src/ui/lifecycle_page.py
src/ui/model_evaluation_page.py
src/ui/state_screener_page.py
src/ui/market_regime_page.py
src/ui/help_texts.py
src/evaluation/signal_validation.py       # 只允许加 metadata 输出，不改核心评估逻辑
```

## Readiness policy 要求

新增 `src/ui/readiness_policy.py`，至少提供 `ReadinessDecision` 数据结构和以下函数：

```python
def evaluate_hmm_state_display(...): ...
def evaluate_hmm_strategy_display(...): ...
def evaluate_hsmm_lifecycle_field_display(...): ...
def evaluate_state_source_boundary(...): ...
def get_default_stage00_policy(...): ...
```

如果 WP-A 的 `ui_readiness_policy` 表存在，可以读取表；如果不存在，必须使用内置保守 policy。表不存在不能导致 UI 崩溃。

默认规则必须包含：

- HMM state label：`state_source` 为 `causal_walk_forward` 时可正常展示；如果 context 是 research 或 `in_sample_explanation`，可展示但必须降级说明。
- HMM posterior probability：只允许作为 `state confidence`；禁止称为上涨概率、下跌概率、买入概率、赚钱概率。
- HMM strategy/backtest：必须有 `causal_cache_id` 或 walk-forward cache metadata；没有 causal cache 时显示 research_only 或阻断。
- HSMM state age：允许 internal_diagnostic 展示。
- HSMM state phase：允许 internal_diagnostic 展示。
- HSMM low/medium/high exit tendency：允许 internal_diagnostic ordinal tendency 展示。
- HSMM numeric `raw_p_exit` / `calibrated_p_exit`：默认隐藏；只有 `probability_status == usable_probability` 且 `readiness_status` 属于 `validated` 或 `decision_ready` 时才可展示。
- HSMM invalid/missing/insufficient fields：隐藏值并显示 fallback reason，不得以 0 填补。
- Next-state tendency：只能显示为 realized historical tendency；除非专门 validation record 允许，不得称为 predicted probability。

## Causal boundary 要求

新增 `src/ui/causal_boundary.py`，至少提供：

```python
def classify_state_source(...): ...
def require_causal_for_strategy(...): ...
def attach_evidence_metadata(...): ...
def audit_no_in_sample_causal_mix(...): ...
```

`audit_no_in_sample_causal_mix` 至少检查：

```text
同一 UI 数据集是否混合 in_sample 与 causal_walk_forward
策略评估是否缺少 causal_cache_id
train_end > trade_date
max_observation_date_used > trade_date
exec_date <= signal_date
```

缺字段时不能默认通过，应输出 `unknown_due_to_missing_metadata`。

## UI 修改要求

### Lifecycle page

`src/ui/lifecycle_page.py` 必须保证：

1. 默认不查询 raw/calibrated `p_exit` 数值列用于展示。
2. 即使表中存在 raw/calibrated `p_exit` 列，也不显示，除非 readiness decision 允许。
3. `exit_tendency_1d/3d/5d/10d/20d` 明确显示为低/中/高倾向，不显示百分比。
4. `next_state_tendency_*` 明确显示为历史 realized profile 的倾向，不显示为模型预测概率。
5. 页面统一说明 HSMM lifecycle 是内部诊断层，不是排序或交易建议。
6. 页面或行级 metadata 至少包含 `run_id`、`profile_mode`、`profile_cutoff_date`、`state_date_policy`、`evidence_level` 或 readiness badge。

### Model evaluation / backtest pages

没有 causal walk-forward cache 时，策略评估区域必须降级为 research-only 或隐藏。

页面文案必须明确样本内状态只能用于历史解释，不能用于策略回测。

HMM 后验概率不得被称为上涨概率。

如果策略净收益未通过基线，状态输出只能显示为研究信号，不显示为 validated signal。

### State screener / market regime pages

展示当前状态时必须显示 `state_source` 或等价解释。缺少因果 metadata 时显示 conservative warning。不展示任何未经 readiness 允许的概率字段。

## 文案审计要求

新增或扩展文本审计测试，禁止以下误导性表达出现在受控 UI 页面：

```text
HMM上涨概率
上涨概率
下跌概率
买入概率
卖出概率
赚钱概率
HSMM预测下一状态概率
p_exit代表下跌概率
p_exit代表上涨概率
```

允许在帮助文本中出现“不是上涨概率”、“不是交易建议”等否定句，但测试需要区分否定语境。

## 测试要求

至少覆盖：

1. `evaluate_hsmm_lifecycle_field_display` 对 state age/phase 返回 allow。
2. numeric `p_exit` 默认 hide。
3. `probability_status` 为 invalid/missing/insufficient_sample 时不显示数值。
4. next-state tendency 只能显示 tendency。
5. `audit_no_in_sample_causal_mix` 能识别混合 `state_source`。
6. 缺少 causal cache 的策略评估返回 research-only 或 block。
7. lifecycle page import 不报错。
8. 受控 UI 文案审计通过。

建议命令：

```bash
python -m compileall -q src tests
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q tests/test_lifecycle_ui_text_policy.py tests/test_lifecycle_text_audit_summary.py
pytest -q -m "not slow"
```

## 本地数据需求

优先使用 V0 已有本地 DB：

```text
data/db/a_share_hmm.duckdb
```

不抓取新数据。

如果 DB 存在，额外执行只读 UI readiness audit：

```bash
python -m src.ui.readiness_policy \
  --db data/db/a_share_hmm.duckdb \
  --audit-lifecycle \
  --output reports/ui_readiness/stage00_wp_c_readiness_audit.md
```

如果不希望 UI 模块带 CLI，可放在 `src/evaluation/ui_readiness_audit.py`，但 UI 页面必须调用同一套 policy 函数，不能复制规则。

## 交付物

Codex 完成后必须提交：

```text
src/ui/readiness_policy.py
src/ui/causal_boundary.py
src/ui/evidence_badges.py             # 如实现 badge helper
tests/test_ui_readiness_policy.py
tests/test_ui_causal_boundary.py
reports/ui_readiness/stage00_wp_c_readiness_audit.md
reports/ui_readiness/stage00_wp_c_readiness_audit.json
```

如修改 UI 页面，必须列出具体页面与改动点。

## 验收标准

本包通过标准：

1. UI readiness policy 单元测试通过。
2. 文案审计通过。
3. lifecycle page 不展示 numeric `p_exit`，除非 policy 显式允许。
4. 无 causal cache 的策略评估不能显示为 causal 或 validated。
5. HMM posterior 不被解释为收益概率。
6. `state_source` 混合会被 audit 识别。
7. registry 表不存在时仍保守运行。
8. 没有抓取新数据。

## 失败降级

如果某个 UI 页面耦合过重，优先完成 policy 与测试，并在页面上增加最小 conservative warning，不做大重构。

如果 WP-A registry 表尚未合并，使用内置默认 policy；合并后再通过后续小包改为读表。

如果本地 DB 缺失，仍完成 policy、unit、text tests，并把 readiness audit 标记为 `skipped_db_missing`。

## Codex 回传格式

请按以下格式回传：

```text
WP: STAGE00_WP_C_ui_readiness_causal_boundary
状态: pass / partial / fail
修改文件:
- ...
运行命令与结果:
- command: ...
  result: ...
UI 页面改动:
- ...
readiness audit:
- report: ...
- numeric p_exit displayed: yes/no
- causal/in_sample mix found: yes/no
本地数据使用情况:
- 使用 data/db/a_share_hmm.duckdb: yes/no
- 是否抓取新数据: no
风险与遗留问题:
- ...
需要我验收的重点:
- ...
```
