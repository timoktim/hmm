# STAGE00_WP_A_evidence_registry

阶段：Stage 00 / 冻结现状与建立证据账本  
工作包编号：WP-A  
并行属性：可与 WP-B、WP-C 并行；本包只负责证据账本、validation run 与 run-artifact 元数据，不改 UI 展示逻辑，不重训模型。  
目标仓库：V0 目前起点模型  
执行者：Codex 线程 A  
日期：2026-06-01

## 1. 背景与目标

当前系统已有 HMM/HSMM 基础能力，但阶段 0 的重点不是提高模型复杂度，而是让每个结论、报告、UI 输出和后续实践判断都能追溯到明确的 `run_id`、`feature_scope_id`、`universe_id`、验证命令、报告路径和 evidence level。

本包目标是建立可审计的证据账本层，包括：

1. 新增或扩展 DuckDB schema，支持模型 evidence registry、validation run、artifact manifest 与 UI readiness policy 的机器可读记录。
2. 提供幂等 migration 和最小读写 API。
3. 提供 CLI/函数把现有报告、测试结果、run metadata 注册到证据账本。
4. 为 WP-B 的 baseline freeze 和 WP-C 的 UI readiness gate 提供稳定数据接口。

## 2. 必须遵守的边界

本包不得做以下事项：

1. 不修改 HMM/HSMM 模型训练算法。
2. 不改 UI 页面展示逻辑；UI gating 由 WP-C 处理。
3. 不重新抓取任何行情或成分股数据。
4. 不把 `p_exit`、HMM posterior 或任何模型概率升级成实践判断。
5. 不删除既有表和既有字段。
6. 不要求存在 git repository；如果 `git rev-parse` 不可用，记录为 `unknown`。

## 3. 建议修改范围

优先修改或新增以下文件：

```text
src/data_pipeline/storage.py
src/evaluation/evidence_registry.py
src/evaluation/run_manifest.py
tests/test_evidence_registry.py
tests/test_validation_runs_registry.py
```

允许在 `src/evaluation/__init__.py` 增加导出，但不要影响现有导入路径。

## 4. Schema 设计要求

请在 `DuckDBStorage.init_schema()` 中加入幂等 schema。必须支持连续执行两次而无错误。

### 4.1 `model_evidence_registry`

建议字段如下；如需微调，请保持语义不弱化。

```sql
CREATE TABLE IF NOT EXISTS model_evidence_registry (
  evidence_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  source_run_id TEXT,
  model_type TEXT NOT NULL,
  model_family TEXT,
  evidence_level TEXT NOT NULL,
  readiness_status TEXT NOT NULL,
  verdict_code TEXT,
  verdict_label TEXT,
  universe_id TEXT,
  universe_version TEXT,
  feature_scope_id TEXT,
  feature_scope_type TEXT,
  feature_version TEXT,
  causal_cache_id TEXT,
  benchmark_id TEXT,
  train_start DATE,
  train_end DATE,
  eval_start DATE,
  eval_end DATE,
  inference_mode TEXT,
  state_source TEXT,
  data_source_policy TEXT,
  execution_calendar TEXT,
  cost_bps DOUBLE,
  profile_mode TEXT,
  profile_cutoff_date DATE,
  state_date_policy TEXT,
  report_path TEXT,
  ui_route TEXT,
  artifact_manifest_json TEXT,
  metrics_json TEXT,
  notes TEXT,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

字段约束：

- `evidence_level` 只允许：`exploratory`、`internal_diagnostic`、`validated_signal`、`decision_support`。
- `readiness_status` 只允许：`blocked`、`research_only`、`internal_only`、`partial`、`validated`、`decision_ready`。
- `run_id + model_type + report_path` 应能稳定生成同一个 `evidence_id`，便于重跑时 upsert。
- 不允许把缺失的 `feature_scope_id` 静默当作 `all`，除非源表中确实已有默认值；缺失时应记录 `missing` 并在 `notes` 中解释。

### 4.2 `validation_runs`

```sql
CREATE TABLE IF NOT EXISTS validation_runs (
  validation_run_id TEXT PRIMARY KEY,
  run_id TEXT,
  evidence_id TEXT,
  validation_type TEXT NOT NULL,
  command TEXT,
  status TEXT NOT NULL,
  verdict_code TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  duration_seconds DOUBLE,
  python_version TEXT,
  duckdb_version TEXT,
  platform TEXT,
  git_sha TEXT,
  db_path TEXT,
  report_dir TEXT,
  metrics_json TEXT,
  warnings_json TEXT,
  created_at TIMESTAMP NOT NULL
);
```

字段约束：

- `status` 只允许：`pass`、`fail`、`skip`、`error`、`unknown`。
- `validation_type` 至少支持：`schema_migration`、`unit_tests`、`lifecycle_report`、`signal_validation`、`baseline_freeze`、`ui_readiness_audit`、`causal_audit`。

### 4.3 `ui_readiness_policy`

WP-C 会消费 readiness policy。本包只负责 schema 和种子策略，不改 UI。

```sql
CREATE TABLE IF NOT EXISTS ui_readiness_policy (
  policy_id TEXT PRIMARY KEY,
  surface TEXT NOT NULL,
  field_name TEXT NOT NULL,
  model_type TEXT,
  required_evidence_level TEXT NOT NULL,
  required_readiness_status TEXT NOT NULL,
  allow_display BOOLEAN NOT NULL,
  display_mode TEXT NOT NULL,
  fallback_text TEXT,
  policy_reason TEXT,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

必须至少 seed 以下策略：

```text
HMM posterior probability: display_mode=state_confidence_only; required_evidence_level=internal_diagnostic; fallback_text=状态概率不是上涨概率
HMM strategy output: display_mode=research_only unless validated_signal
HSMM state_age: display_mode=display; required_evidence_level=internal_diagnostic
HSMM state_phase: display_mode=display; required_evidence_level=internal_diagnostic
HSMM exit_tendency_low_medium_high: display_mode=internal_ordinal; required_evidence_level=internal_diagnostic
HSMM numeric_p_exit: display_mode=hide_unless_usable_probability; required_readiness_status=validated
HSMM invalid_probability: display_mode=hide
In-sample state: display_mode=research_only; fallback_text=样本内解释，不能用于因果回测
Causal walk-forward state: display_mode=display_if_cache_valid
```

## 5. API / CLI 要求

新增 `src/evaluation/evidence_registry.py`，至少包含：

```python
class EvidenceLevel(str, Enum): ...
class ReadinessStatus(str, Enum): ...
@dataclass
class EvidenceRecord: ...
@dataclass
class ValidationRunRecord: ...

def make_evidence_id(run_id: str, model_type: str, report_path: str | None) -> str: ...
def upsert_evidence_record(db_path: str, record: EvidenceRecord) -> str: ...
def upsert_validation_run(db_path: str, record: ValidationRunRecord) -> str: ...
def list_evidence_for_run(db_path: str, run_id: str) -> pd.DataFrame: ...
def get_latest_evidence(db_path: str, model_type: str, run_id: str | None = None) -> dict | None: ...
def seed_ui_readiness_policy(db_path: str) -> int: ...
```

同时提供 CLI：

```bash
python -m src.evaluation.evidence_registry \
  --db data/db/a_share_hmm.duckdb \
  --seed-policy \
  --print-summary
```

可选支持：

```bash
python -m src.evaluation.evidence_registry \
  --db data/db/a_share_hmm.duckdb \
  --register-report reports/signal_validation/primary_20260529_main/summary.md \
  --run-id <run_id> \
  --model-type hmm \
  --evidence-level internal_diagnostic \
  --readiness-status research_only
```

## 6. 与现有表的衔接要求

需要能从以下表读取已存在元数据。表不存在时不报未捕获异常，而是返回空结果并在 `notes` 或 warnings 中说明。

```text
model_runs
sector_state_daily
walk_forward_cache_runs
walk_forward_state_cache
hsmm_model_runs
hsmm_model_checkpoints
hsmm_state_daily
hsmm_lifecycle_ui_daily
hsmm_lifecycle_duration_profile
hsmm_next_state_tendency_profile
```

如果现有 run 表已经有 `universe_id`、`feature_scope_id`、`feature_scope_type`，注册时必须尽量继承，不得覆盖为硬编码默认值。

## 7. 测试要求

必须新增或补充测试，至少覆盖：

1. `DuckDBStorage.init_schema()` 连续执行两次通过。
2. 三张新表存在，字段齐全。
3. `seed_ui_readiness_policy()` 重复执行不会产生重复记录。
4. `make_evidence_id()` 对同一输入稳定，对不同 report/run/model 有区分。
5. `upsert_evidence_record()` 可插入并更新同一 evidence。
6. 非法 `evidence_level`、非法 `readiness_status` 会被拒绝或规范化失败。
7. 表不存在或本地 DB 不含某些 run 时，CLI 返回非 0 或清晰 warning，不静默成功。

建议命令：

```bash
python -m compileall -q src tests
pytest -q tests/test_evidence_registry.py tests/test_validation_runs_registry.py
pytest -q -m "not slow"
```

## 8. 本地数据测试需求

使用 V0 现有本地数据，默认数据库路径：

```text
data/db/a_share_hmm.duckdb
```

本包不需要抓取新数据。若本地 DB 不存在，只跑 schema/unit tests；若 DB 存在，额外执行：

```bash
python -m src.evaluation.evidence_registry --db data/db/a_share_hmm.duckdb --seed-policy --print-summary
```

并导出：

```text
reports/evidence_registry/stage00_wp_a_registry_summary.md
reports/evidence_registry/stage00_wp_a_registry_summary.json
```

## 9. 交付物

Codex 完成后必须提交：

```text
src/evaluation/evidence_registry.py
src/evaluation/run_manifest.py            # 若实现独立 run manifest 工具
tests/test_evidence_registry.py
tests/test_validation_runs_registry.py
reports/evidence_registry/stage00_wp_a_registry_summary.md
reports/evidence_registry/stage00_wp_a_registry_summary.json
```

若修改 `storage.py`，必须说明新增 schema 和 migration 是否幂等。

## 10. 验收标准

本包通过标准：

1. 新 schema 幂等创建。
2. 三张核心表能被查询。
3. policy seed 不重复。
4. 至少能注册一条 HMM 或 HSMM evidence 记录。
5. 所有新增测试通过。
6. `pytest -q -m "not slow"` 通过，或若因本地环境/依赖失败，必须给出完整失败日志和最小复现。
7. 输出 summary 中必须明确：本包没有改变模型训练、没有改 UI 展示、没有抓取新数据。

## 11. 失败降级方案

如果无法安全修改 `storage.py`，则新增独立 migration 函数：

```python
ensure_evidence_registry_schema(db_path: str) -> None
```

并在 CLI 和测试中调用。不得让阶段 0 因 schema 集成点卡住。

如果本地 DB 缺失，仍应完成内存 DuckDB 或临时文件 DuckDB 的 schema 测试。

## 12. Codex 回传格式

请按以下格式回传：

```text
WP: STAGE00_WP_A_evidence_registry
状态: pass / partial / fail
修改文件:
- ...
新增表:
- ...
运行命令与结果:
- command: ...
  result: ...
生成报告:
- ...
本地数据使用情况:
- 使用 data/db/a_share_hmm.duckdb: yes/no
- 是否抓取新数据: no
风险与遗留问题:
- ...
需要我验收的重点:
- ...
```
