# WORK PACKAGE: STAGE03R-WP6.1 — 多 horizon hazard 预测与校准重生成

> 交付给 Codex 在**带本地 DuckDB 的环境**执行。本文件即任务书，可整篇粘贴给 Codex。
> 目标：把 hazard 退出概率从"只有 1 日"补到 3/5/10/20 日，并**诚实地确定哪些 horizon 真的可校准**。

---

## 0. 执行须知（Codex 先读这一节）

- **运行环境**：必须在本地存在且可读 `data/db/a_share_hmm.duckdb` 的机器上运行。以**只读**方式打开 DB。
- **分支**：从 WP6 的分支拉新分支（WP6 尚未合并，本 WP 依赖它的 `hazard_readiness_matrix.py`）：
  ```bash
  git fetch origin
  git checkout stage03r/wp6-hazard-readiness-matrix
  git checkout -b stage03r/wp6.1-multi-horizon-hazard-regen
  ```
  （若届时 WP6 已合并进 main，则改为从 `origin/main` 拉。）
- **诚实性强制要求（最重要）**：这是一个"**重生成 + 诊断**"工作包，不是"想办法让它通过"的工作包。
  - **禁止**为了让 3/5/10/20 达到 `usable_probability` 而调松阈值、改 split、挑数据、改算法。
  - 某个 horizon 若样本不足或过不了 Brier 门槛，就**如实**标 `insufficient_sample` / `baseline_only`，并在报告里写清楚。**那也是合格交付**——它回答了"长 horizon 到底能不能校准"这个未知数。
- **边界（不得越界）**：
  - 不改 HMM/HSMM 训练算法，不重训 HMM/HSMM。
  - 不做任何外部数据抓取（全程 `--no-fetch` / 只读本地 DB）。
  - 不接入 UI、不接入排序/交易、不生成 decision-ready 输出（WP7/WP8 维持 blocked）。
  - **不提交** DuckDB / WAL / cache / 模型产物 / 任何私有绝对路径。
  - 不削弱既有的 purged/embargoed 防泄漏切分（`test_exit_target_leakage_purge.py` 的保证必须仍然成立）。

---

## 1. 背景（为什么做）

- 当前 Stage03R WP6 的 readiness matrix：`calibration_horizons = [1]`，3/5/10/20 日因缺校准证据被降级为 `baseline_only`。
- **根因不是代码能力缺失，而是产物被截断**：committed 的 `reports/stage03r/duration_hazard_logistic_predictions_sample.csv` 被 `write_hazard_outputs(max_predictions=5000)` 用 `predictions.head(5000)` 截断；预测按 `horizon_days` 排序，前 5000 行恰好全是 h=1，于是下游 WP5 isotonic 校准只看到 h=1。
- 三段流水线（`exit_target_dataset` → `duration_hazard` → `hazard_isotonic_calibration`）代码层**已全链路支持多 horizon**，默认就是 `--horizons 1,3,5,10,20`，且 WP4 age-bucket baseline 已在同一份 DB 数据上跑出全部 5 个 horizon（115 slice）——证明数据与流水线都能产多 horizon。
- 因此本 WP = 用真实 DB 重跑全 horizon 预测+校准、刷新 readiness matrix、并堵上截断这个会复发的坑。

---

## 2. 范围

**纳入（IN）**
1. 用 `--db` 模式、`--horizons 1,3,5,10,20` 从真实 DuckDB 重新生成**全 horizon** hazard 预测（**不要**再用截断的 sample CSV 作校准输入）。
2. 对全 horizon 预测重新逐 horizon 拟合 isotonic 校准。
3. 用新的预测+校准产物重新生成 WP6 readiness matrix。
4. **堵截断坑**：保证"喂给校准的预测"是**未截断的全 horizon** 集合；若仍要保留一份小的 committed *sample*，把行数上限改成**按 horizon 分层**（每个 horizon 都有代表行），生产/校准路径绝不能再静默丢 horizon。
5. **补测试**：新增一个断言"多 horizon 端到端不丢失"的测试（合成数据含 {1,3,5,10,20}，断言预测/校准产物覆盖全部 horizon，且分层 sample writer 不丢 horizon）。当前测试只实际验证了 h=1。
6. **产出诚实裁定**：报告里逐 horizon 给出 readiness 状态与 Brier（calibrated vs raw、calibrated vs age-bucket baseline），并写一份简短 verdict。

**排除（OUT）**
- 不重训/不改 HMM/HSMM；不改 hazard/calibration 的核心算法（只准改"产物写出/截断"与测试）。
- 不为通过而调参；不强行升 `usable_probability`。
- 不接 UI / 排序 / 交易 / decision engine。
- 不提交 DB/WAL/cache/私有路径。

---

## 3. 执行步骤（含命令）

> 注：以下命令中，凡标注 `【确认】` 的参数名，请先用 `python -m <module> --help` 核对真实参数名再执行，不要盲跑。已知确定的命令逐字给出。

### Step A. 准备
```bash
# 在仓库根目录，已建好 wp6.1 分支
.venv/bin/python -m compileall -q src tests
ls -l data/db/a_share_hmm.duckdb   # 确认 DB 存在
```

### Step B. 核对三个生成器的 CLI（务必先做）
```bash
.venv/bin/python -m src.models.duration_hazard --help
.venv/bin/python -m src.evaluation.hazard_isotonic_calibration --help
.venv/bin/python -m src.evaluation.exit_target_dataset --help
.venv/bin/python -m src.evaluation.hazard_readiness_matrix --help
```
确认以下点：`duration_hazard` 的 `--db`、`--horizons`、`--max-predictions`、预测输出路径参数；`--db` 模式是否内部经 `_dataset_from_db` 重建 exit-target 数据集（应是，则 Step C 可跳过独立建集）；校准的输入预测参数与输出参数；readiness matrix 的输入/输出参数（见 Step E 已知命令）。

### Step C.（可选）独立重建 exit-target 数据集
如果 `duration_hazard --db` 模式已内部重建数据集，则跳过本步。若需独立产物：
```bash
.venv/bin/python -m src.evaluation.exit_target_dataset \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --horizons 1,3,5,10,20 \
  --output reports/stage03r/exit_target_dataset_full.csv \
  --no-fetch                       # 【确认】参数名
```

### Step D. 全 horizon 重生成 hazard 预测（关键：不要截断）
```bash
.venv/bin/python -m src.models.duration_hazard \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --horizons 1,3,5,10,20 \
  --predictions-output reports/stage03r/duration_hazard_logistic_predictions_full.csv \  # 【确认】输出参数名
  --max-predictions 0 \            # 【确认】用"不截断/足够大"的方式，确保 5 个 horizon 全部写出
  --no-fetch
```
- **校验**：产物必须含全部 5 个 horizon。
  ```bash
  .venv/bin/python - <<'PY'
import pandas as pd
df = pd.read_csv("reports/stage03r/duration_hazard_logistic_predictions_full.csv")
print(sorted(df["horizon_days"].astype(int).unique()))   # 期望 [1, 3, 5, 10, 20]
print(df.groupby("horizon_days").size())
PY
  ```
  若仍只见 h=1 → 说明截断仍在生效，回到 Step F 先改写出逻辑，再重跑本步。

### Step E. 逐 horizon 重新校准
```bash
.venv/bin/python -m src.evaluation.hazard_isotonic_calibration \
  --hazard-predictions reports/stage03r/duration_hazard_logistic_predictions_full.csv \  # 用全 horizon 预测
  --output reports/stage03r/hazard_isotonic_calibration_report.md \                       # 【确认】参数名
  --summary-json reports/stage03r/hazard_isotonic_calibration_report.json \               # 【确认】参数名
  --no-fetch
```
- **校验**：`hazard_isotonic_calibration_report.json` 的 `horizons` 应不再是 `[1]`。

### Step F. 堵截断坑 + 补测试（唯一允许的代码改动）
- 定位 `src/models/duration_hazard.py` 里的 `write_hazard_outputs`（含 `max_predictions` 与 `result.predictions.head(max_predictions)`）。
- 改动要求（取最小且清晰的实现）：
  1. 用于**校准输入**的预测必须是**未截断全 horizon**（首选 `--db` 全量直出，或显式 full 输出文件）。
  2. 若仍保留小的 committed *sample*，把上限改为**按 horizon 分层取样**（如对 `horizon_days` 分组各取 `max_predictions // n_horizons` 行），保证每个 horizon 都有代表行；绝不能再出现"sample 只剩单一 horizon"。
- 在 `tests/test_duration_hazard_baseline.py`（或 `tests/test_hazard_isotonic_calibration.py`）新增测试：
  - 合成数据含 `horizon_days ∈ {1,3,5,10,20}`；
  - 断言预测/校准/分层 sample 产物中 `horizon_days` 唯一值覆盖全部输入 horizon（即**任一 horizon 不被静默丢弃**）；
  - 保持确定性（固定随机种子）。

### Step G. 重新生成 readiness matrix（指向新产物）
```bash
.venv/bin/python -m src.evaluation.hazard_readiness_matrix \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --hazard-predictions reports/stage03r/duration_hazard_logistic_predictions_full.csv \
  --hazard-calibration reports/stage03r/hazard_isotonic_calibration_report.json \
  --age-bucket-baseline reports/stage03r/age_bucket_baseline_report.json \
  --output reports/stage03r/hazard_readiness_matrix_report.md \
  --summary-json reports/stage03r/hazard_readiness_matrix_report.json \
  --no-fetch
```

### Step H. 跑全部门禁与目标测试
```bash
.venv/bin/pytest -q \
  tests/test_exit_target_dataset.py \
  tests/test_exit_target_leakage_purge.py \
  tests/test_duration_hazard_baseline.py \
  tests/test_age_bucket_baseline.py \
  tests/test_hazard_isotonic_calibration.py \
  tests/test_hazard_readiness_matrix.py
bash scripts/stage03r_exit_target_gate.sh
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
bash scripts/stage03_preflight_gate.sh
```

### Step I. 写裁定 + 提交
- 新建 `reports/stage03r/multi_horizon_hazard_verdict.md`，逐 horizon 给出：readiness 状态计数、calibrated-vs-raw Brier、calibrated-vs-baseline Brier、结论（该 horizon 是 `usable_probability` / `baseline_only` / `insufficient_sample`），并用 2-3 句总结"多 horizon hazard 是否可行"。
- 提交（**只提交报告与代码/测试，不提交 DB/cache**），按下方 PR 模板写描述。

---

## 4. 验收门槛

- [ ] 4 个 gate 脚本全部 `pass`；`check_no_private_paths.sh` = `PRIVATE_PATH_HYGIENE=pass`；`validate_stage01_no_private_db.sh` = `pass`。
- [ ] 未提交任何 `*.duckdb` / `*.wal` / `data/cache/*` / 私有绝对路径（git status 干净，hygiene 通过）。
- [ ] 预测产物 `horizon_days` 覆盖 `[1,3,5,10,20]`；校准报告 `horizons` 不再是 `[1]`。
- [ ] readiness matrix 的 `calibration_horizons` 反映了**所有有足够样本的** horizon；样本确实不足的 horizon 显式为 `insufficient_sample`（而非"因输入缺失而被动 baseline_only"）。
- [ ] readiness matrix 的降级语义仍正确：horizon 进 join key、缺校准 horizon 不会被误升为 `usable_probability`（沿用 WP6 逻辑，不改）。
- [ ] 新增多 horizon 测试通过；原有 6 个测试文件全部仍通过（WP6 基线为 51 passed）。
- [ ] 确定性：固定种子下重跑，summary 计数可复现。
- [ ] `verdict.md` 逐 horizon 给出诚实结论；**若长 horizon 不可用，如实记录即视为合格**。

---

## 5. 交付物

- `reports/stage03r/duration_hazard_logistic_predictions_full.csv`（全 horizon；若大可只提交分层 sample，但校准须用过全量）
- `reports/stage03r/hazard_isotonic_calibration_report.{md,json}`（多 horizon）
- `reports/stage03r/hazard_readiness_matrix_report.{md,json}`（刷新）
- `reports/stage03r/multi_horizon_hazard_verdict.md`（逐 horizon 裁定）
- `src/models/duration_hazard.py` 截断硬化 diff
- 新增多 horizon 测试
- 工作包索引更新（若仓库有 `docs/indexes/WORK_PACKAGE_INDEX.md`，登记 WP6.1）

---

## 6. 风险与诚实性说明（必须在 PR "Risks" 里复述）

- 长 horizon（10/20 日）统计上更难校准：删失更多、有效独立样本更少、horizon-bleed 风险更大。**结果很可能是部分长 horizon = `insufficient_sample` 或过不了 Brier 门槛——这是可接受且有信息量的结论，不得通过调参强行翻盘。**
- 必须保留 purged/embargoed 切分；不得因为要"凑够样本"而缩小 embargo。
- 本 WP 不让多 horizon 概率进入任何实践判断/排序/UI；它只把"可行性"这个未知数变成已知，供后续 WP7/决策层规划用。
- 复现依赖本地未提交的 `a_share_hmm.duckdb`；CI/无 DB 环境只能跑合成测试，不能复现真实数值——在 PR 注明。

---

## 7. PR 描述模板（沿用 WP6 结构）

```
## Summary
Implements STAGE03R-WP6.1: regenerate multi-horizon (1/3/5/10/20) hazard
predictions and isotonic calibration from the local DuckDB, refresh the WP6
readiness matrix, and harden the prediction-artifact truncation that previously
collapsed the committed sample to horizon=1.

## Readiness results
- report status: <pass/…>
- row_count / usable_probability_count / ordinal_only / baseline_only /
  insufficient_sample / invalid: <…>

## Horizon coverage
- expected_horizons: [1,3,5,10,20]
- calibration_horizons: <…>            # 期望不再是 [1]
- missing_calibration_horizons: <…>

## Per-horizon verdict
<逐 horizon: usable_probability / baseline_only / insufficient_sample + 原因>

## Brier summaries
- calibrated vs raw: <…>
- calibrated vs age-bucket baseline: <…>

## Local DB validation
- local DB path: data/db/a_share_hmm.duckdb
- DB found / opened read-only: yes / yes
- DuckDB committed: no

## Boundary
- external data fetch: no
- training algorithm modified: no
- HMM/HSMM retrained: no
- decision-ready / trading outputs: no (WP7/WP8 remain blocked)
- DuckDB/WAL/cache/private path committed: no

## Truncation hardening
<说明 write_hazard_outputs 改动：校准输入用全量；committed sample 改为按 horizon 分层>

## Validation
<compileall + 6+1 tests + 4 gate scripts 的实际输出>

## Risks
<复述第 6 节：长 horizon 可能不可校准、诚实记录、复现依赖本地 DB>
```

---

## 8. 一句话任务（TL;DR，可单独发给 Codex）

> 在带 `data/db/a_share_hmm.duckdb` 的本地环境，从 `stage03r/wp6-hazard-readiness-matrix` 拉分支 `stage03r/wp6.1-multi-horizon-hazard-regen`；用 `--db` 模式、`--horizons 1,3,5,10,20` **重生成全 horizon hazard 预测**（不要用截断到 5000 行的 sample CSV），逐 horizon 重新 isotonic 校准，刷新 WP6 readiness matrix；把 `duration_hazard.write_hazard_outputs` 的 `max_predictions` 截断改成"校准用全量、committed sample 按 horizon 分层"，并补一个多 horizon 端到端测试；跑通 6+1 测试与 4 个 gate 脚本；新建 `reports/stage03r/multi_horizon_hazard_verdict.md` 逐 horizon 给出**诚实**裁定（不得为通过而调参，长 horizon 不可用就如实标 `insufficient_sample`/`baseline_only`）；只提交报告与代码/测试，**不提交 DB/cache/私有路径**。
