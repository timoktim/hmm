# A股板块 HMM/HSMM 分析器 — 代码审计报告

- **日期**：2026-06-03
- **范围**：全仓库（src/ 全量、app.py、scripts/、shell 脚本、CI、依赖、关键文档）
- **方式**：只读静态审计 + 文档交叉验证 + 多路并行专项审计（回测因果性 / HSMM 模型 / 数据管道）。**未运行代码**（沙箱无 venv），结论为静态推理并与既有测试契约和团队评估文档相互印证。
- **声明**：本次审计**未改动任何源代码或既有文档**，仅新增本报告。
- **威胁模型前提**：本工具为**本地单机、研究用途**，不自动下单、不对外提供网络服务（Streamlit 默认 localhost），无鉴权/多用户。因此安全风险天然偏低，审计重心放在**量化功能的正确性**。

---

## 0. 执行摘要

**架构与因果纪律是本项目的强项，没有发现高危的"未来函数/前视偏差"。** 前向滤波概率、walk-forward 缓存血缘校验、UI 概率门控、特征工程的后向 rolling 都做得很认真。

真正的短板在两处，而且团队自评文档已经承认，本次审计进一步定位了根因：

1. **板块 HMM 策略有效性 = `Weak`**（团队结论）：扣 0.1% 单边成本后打不过 RS20 轮动，明显弱于全板块等权。→ 工具应定位为"状态识别 / nowcast"，**不是可盈利策略**。
2. **HSMM 生命周期模型 = `InvalidDueToCalibrationFailure`**（团队结论）：退出概率校准缺乏基本单调性。→ 审计找到很可能的根因：**校准目标错配**（state_id 预测 vs label 实际）与**校准训练集 horizon 泄漏**。

> 当前最该投入的不是堆新功能或做 HSMM UI，而是**修校准 + 补数据校验 + 修正覆盖率/指数口径**——这与团队文档"先修 calibration 再做 UI"的判断一致。

严重度统计（本报告口径）：

| 类别 | 高 | 中 | 低 |
|------|----|----|----|
| 安全 | 0 | 2 | 3 |
| 功能（回测/HMM/HSMM/数据） | 3 | 11 | 9 |
| 工程健壮性 | 0 | 3 | 1 |

---

## 1. 安全漏洞

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| S1 | **导入板块池 JSON 的 SQL 列名注入**：`import_universe_json` 把上传 JSON 中 `basket` 字典的**任意 key 当作 SQL 列标识符**拼进 `INSERT INTO custom_stock_basket ({col_sql})`，未做白名单/转义。`upsert_df` 用 f-string 拼接列名与表名 | `storage.py:1605-1609` → `upsert_df` `storage.py:1327-1352` | 中（本地、需诱导用户导入恶意文件，概率低） |
| S2 | **pickle 缓存反序列化**：`pd.read_pickle()` 直接读 `data/cache/*.pkl`；若缓存目录被其他进程/用户写入，下次读取即可触发任意代码执行 | `akshare_client.py:150-153, 234` | 低-中（本地；打包脚本已排除 cache 目录） |
| S3 | **明文 HTTP 抓取成分股**：`http://q.10jqka.com.cn/...`（非 HTTPS），响应 HTML 直接 `pd.read_html` 解析 → 中间人可篡改成分股名单 | `ths_helpers.py:59,67` | 低-中（数据完整性，非机密泄露） |
| S4 | **执行第三方 JS**：用 py-mini-racer `eval` akshare 包内 `ths.js` 生成 cookie。运行在 V8 沙箱、无 Node，相对可控，但属供应链执行面 | `ths_helpers.py:33` | 低 |
| S5 | **依赖无上界 + akshare 供应链脆弱**：`requirements.txt` 全部 `>=` 无上界；`akshare`/`hmmlearn`/`streamlit`/`pandas` 任一破坏性升级都会让"全新安装首次运行"静默损坏（评估包不含 venv，首次需重装依赖） | `requirements.txt` 全文 | 中（稳定性/供应链） |

### 已确认安全的点（正面）

- 子进程 `_call_akshare_subprocess` 用 `[sys.executable, "-c", code, payload, out_path]` 形式，**非 shell 调用**，kwargs 以 JSON 数据经 argv 传入、不拼进代码字符串 → **无命令注入**（`akshare_client.py:166-212`）。
- **无硬编码密钥/token**、无 `.env` 入库、无 `verify=False` 关闭 SSL 校验、无 `unsafe_allow_html`（无 Streamlit XSS 面）、Streamlit 未绑 `0.0.0.0`。
- 其余动态 SQL 几乎全部使用 `?` 占位符参数化；f-string 拼接的仅为**内部白名单表名**（如 `HSMM_RUN_CASCADE_TABLES`）或经 `int()`/`quote_identifier()` 处理的标识符，无外部注入面。
- shell 脚本（`*.command`、`scripts/*.sh`）均 `set -euo pipefail`、参数固定，无注入。

---

## 2. 功能性缺陷 — 回测 / 评估 / 板块 HMM

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| F1 | **默认 open 执行路径多计建仓日日内收益**：`close` 路径建仓日收益记 0（保守，有测试断言）；但默认的 `open` 路径让新权重在执行日 t+1 就吃 open→close 日内收益。两路径对"建仓日是否计收益"口径不一致，趋势类信号下 open 路径系统性偏乐观，且未建模滑点/冲击 | `sector_rotation.py:474-495` | 中 |
| F2 | **`evaluate_forward_returns` 默认 `in_sample_display` 且函数层无护栏**：用样本内状态成员资格统计未来收益＝经典"样本内当样本外有效性证据"。仅靠 UI 层 `st.warning` 兜底；任何脚本/测试直接调用会静默得到泄漏结果，返回值无强制"不可作有效性证据"标记 | `model_evaluation.py:84-161`（默认值 :90） | 中 |
| F3 | **交易成本口径不透明**：单/双边语义未声明，无卖出印花税不对称、无最小费用；对高换仓（小 `rebalance_days`）策略影响放大。当前对 L1 换手 `Σ|new−old|` 乘单一费率，等价双边各 0.1% | `sector_rotation.py:479-495`，`_turnover:426` | 低 |
| F4 | **持仓板块当日收益缺失（停牌/缺口）按 0 处理**：`returns.get(id, 0.0)` + `.fillna(0)`；停牌复牌跳空时系统性低估波动与回撤 | `sector_rotation.py:431-439, 458-460` | 低 |
| F5 | **`evaluate_state_stability` 转移概率基于样本内状态**：作为描述性统计可接受，但若被解读为样本外转移预测则同 F2 类泄漏，且此处无 UI 警告上下文 | `model_evaluation.py:184-187` | 低 |

**板块 HMM 训练/标注本身**：每日 `prob_*` 经 `filtered_predict_proba`（标准前向滤波 P(state_t|obs≤t)，逐序列隔离、无跨板块泄漏）确认**因果**；`label_states` 的"状态→标签"映射用全窗口同期特征均值（无监督 regime 标注的固有性质），历史日期标签隐含未来信息——属**口径声明问题，非单日前视**。

---

## 3. 功能性缺陷 — HSMM 生命周期 + 退出概率校准

> 这是**最值得优先修复**的一块。`InvalidDueToCalibrationFailure` 很可能由 H1/H2 直接造成。

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| H1 | **校准目标错配**：预测的 `raw_p_exit` 是按 **state_id**-时长计算的量，而"实际退出"按 **state_label 变化**度量。相邻 state_id 共享同一 label 时，state_id 退出不等于 label 退出 → 模型被读成系统性过度自信，破坏校准单调性 | `hsmm_exit_calibration.py:38-43`（对比正确做法见 `hsmm_exit_targets.py` 区分 state_id/display_label） | 中（疑似 Invalid 主因） |
| H2 | **校准训练/验证集 horizon 泄漏**：校准器训练取 `trade_date<=train_end`，但末尾 `h` 行的"实际退出"由 `idx+1..idx+h` 计算、落进验证期 → 训练标签偷看了 train_end 之后最多 `horizon` 个交易日。10/20 日 horizon 泄漏更明显 | `hsmm_exit_calibration.py:111-118` + 调用 `hsmm_diagnostics.py:1163-1172` | 中 |
| H3 | **duration PMF 忽略右删失/截断**：仍在持续的末段、以及真实长度超过 `max_duration` 的段，全部当"已完成时长"计数（且尾桶 `pmf[max_duration-1]` 被灌满）。无右删失处理（尽管 episode 表里有 `is_right_censored` 字段）→ `p_exit`、`expected_remaining_days`、`duration_percentile` 对长寿命状态系统性偏短 | `hsmm_model.py:463-464` | 中 |
| H4 | **`age==max_duration` 时 `p_exit` 被强制 =1.0**：截断边界处幸存质量与退出质量都塌缩到同一末桶，比值恒为 1（"必退出"），是截断伪影而非真实预测（`age>max_duration` 正确返回 NaN，但边界值未被测试覆盖） | `hsmm_model.py:319-328` | 中 |
| H5 | **`fit_empirical_exit_calibrator` 默认 `train_end_date=None`**：默认在同一批行上既算经验退出率又做校准（样本内/前视）。规范诊断调用方传了切分，但其它调用方静默踩坑 | `hsmm_exit_calibration.py:111-136` | 低-中 |
| H6 | **左删失段偏置**：DP parse 从 `train_start` 起，窗口前已开始的段 age 被低估 → `duration_percentile`/phase/`p_exit` 偏置；仅 episode 打 `is_left_censored` 标记，每日概率本身未抑制 | `hsmm_walk_forward.py:536-540` | 低 |
| H7 | **prefix 模式 `label_state_age_days` 塌缩为 id-age**：`endpoint_snapshot_from_dp` 把 by_label 直接等于 by_id；walk-forward 里靠 `_stitch_state_age_by_label` 重算覆盖，故落库一致，但直接调用 prefix 快照 API 会拿到错误 label age | `hsmm_model.py:243-247` | 低 |
| H8 | **超出支撑域的行（`raw_p_exit=NaN`）仍可经全局兜底拿到校准退出概率**：其 bucket 为 NaN 被丢出率表，但 `_lookup_rate` 落到 horizon-only 全局率，给一个模型本应"未定义"的行返回了自信数值 | `hsmm_exit_calibration.py:139-158` | 低 |
| H9 | **`duration_percentile` 是无条件 CDF** `P(D≤age)`，与生存条件化的 `p_exit`/`expected_remaining_days` 概念不一致（且作为校准分桶输入） | `hsmm_model.py:304-310` | 低 |

### HSMM 正面发现

- 特征**不含 forward/future return**（`hsmm_features.py` 全后向）。
- semi-Markov Viterbi 严格（非把普通 HMM Viterbi 当 HSMM），多 sector 训练**无跨 sector 转移泄漏**。
- prefix 与 legacy 两条解码路径**都因果**（窗口截断至 snapshot_date，scaler 仅在训练数据上 fit）。
- 对数空间数值防护到位（clip 到 EPS、零转移 -inf、方差下限、空序列与全 -inf 回溯均有守卫），numba 与 纯 Python DP 核逐位一致。
- 退出概率的 as-of 处理正确（正例需 realized exit ≤ cutoff，负例需整段 horizon 窗 ≤ cutoff）。

---

## 4. 功能性缺陷 — 数据管道 / 市场宽度 / 大盘 / 自定义池 / 校验

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| D1 | **OHLCV 入库校验过弱且未全覆盖**：`validate_ohlcv` 仅查必填列/空/`close<=0`；**不查**重复 `trade_date`、`high<low`、`close` 越界、负成交量/额、价格巨缺口。且**只在板块 `board_hist` 路径调用**，个股/指数/基准/全A 路径均不校验 → 脏数据可直接入库污染宽度与大盘特征 | `validators.py:9-19`；调用仅 `updater.py:222` | **高**（唯一入库闸门，漏检面过大） |
| D2 | **`local_sample` 覆盖率自我循环**：`coverage_ratio=effective/total≈1` 恒成立（当日出现的票几乎都有 daily_ret），且 `expected_count=total_count`，无法反映"本地样本相对全A 的真实覆盖"。下游降级/告警据此会**高估本地样本代表性** | `market_updater.py:365-380` | **高**（口径误导） |
| D3 | **自定义池权重随停牌动态漂移**：等权/自定义权重在"逐日有效成员子集"上重归一化，停牌成员权重被临时分摊给其他成员，指数收益偏离设定权重，停牌多时放大波动（与"固定权重+停牌记0"口径不同） | `custom_basket_features.py:49-71` | **高**（指数口径） |
| D4 | **涨跌停用 9.8% 单阈值近似**：未按 创业板/科创板/北交所(±20%/±30%)、ST(±5%) 区分，且基于 qfq 复权价而非原始涨跌幅 → 涨跌停宽度统计系统性高估（创业板等普通波动被当涨停）+ 漏计（ST 5% 涨停被漏） | `market_updater.py:362-363` | 中 |
| D5 | **多表独立增量、无统一"目标最新交易日"对齐**：指数、个股 OHLCV、宽度各自增量、彼此不校验最新日 → 可能指数到 T、宽度到 T-1 静默错位 | `updater.py` / `market_updater.py` / `market_features.py` | 中 |
| D6 | **`_lookback_start` 用自然日近似交易日窗口**：默认回补 10 自然日；长假叠加周末或长期停牌后，回补窗可能整段落在非交易区间 → 本轮拿不到新数据、不报错、缺口静默延续 | `updater.py:62-69` | 中 |
| D7 | **大盘宽度降级是"全有或全无"**：`effective_use_breadth = use_breadth and not warning`，而 warning 由全样本 `.all()` 门槛触发 → 最近一日 full_market 不达标即对**整段训练**放弃宽度特征，过度保守 | `market_hmm.py:90, 202-207` | 中 |
| D8 | **低覆盖自定义池静默入库**："有效成员<50%" 只在 `custom_basket_quality_frame` 展示，不拦截 `build_custom_basket_ohlcv`（仅完全空才返回空） | `custom_basket_features.py:81-90` | 中 |
| D9 | **大盘状态标签全样本 in-sample 拟合**：`model.fit` 与 `label_market_states` 用全窗口；每日 `prob_*` 因果，但 `state_label` 映射含未来信息（轻微前视，回测口径需声明） | `market_hmm.py:111-137, 225` | 中 |
| D10 | 最新交易日仅探测前 5 只股票、取首个成功者（非 `max`）；这 5 只停牌/退市则误判偏旧并错误 `skip_completed` | `market_updater.py:84` | 低 |
| D11 | `label_market_states` 并列/少样本时 RiskOn 与 RiskOff 可能映射到同一状态，三态退化为两态；`BASE_MARKET_FEATURE_COLUMNS` 的 drawdown 缺 zz500、口径不对称 | `market_hmm.py:134-136`；`market_features.py:26-28` | 低 |
| D12 | 自定义池 `codes`（SQL IN）未 zfill 而 `member_weights` zfill → merge key 两边不一致隐患；常数序列 `std=0`→z 全 NaN 被静默丢弃；全栈依赖本地时区（`date.today()`/`Timestamp.now()`，非东八区部署跨日判定有风险） | `custom_basket_features.py:22 vs 40`；`market_updater.py:374`；`dates.py` | 低 |

### 数据层正面发现

- `storage.upsert_df` 为 `ON CONFLICT DO UPDATE/NOTHING`，增量重叠回抓**覆盖而非重复**（无重复行风险）。
- 宽度 `below_ma20 = ma20_valid - above_ma20`、`above_ma20_ratio` 分母用 `ma20_valid_count`，口径自洽；`ma_sparse` 警告兜底正确。
- walk-forward 回测缓存契约**稳健**：`cache_key` 由含 `data_snapshot_hash`（对 OHLCV 全列摘要）的 `lineage_hash` 派生，读取时校验 lineage/feature_lineage/feature_scope/universe/row_count 一致，并强制 `max_observation_date_used <= trade_date`（因果保护）；样本内演示路径有显式 `allow_in_sample_demo` 拦截（`sector_rotation.py:661`）。
- UI readiness 门控**保守可靠**：数值型 `p_exit` 默认隐藏，仅当 `usable_probability` + 已验证 + 策略显式允许才显示；无效概率状态→隐藏并警告"不要用 0 填充缺失概率"（`readiness_policy.py:561-598`）。**已知无效的 HSMM 数值退出概率被正确挡在 UI 之外**，只展示序数化 low/medium/high 倾向与状态年龄/阶段。

---

## 5. 工程健壮性

| # | 问题 | 位置/说明 | 严重度 |
|---|------|-----------|--------|
| E1 | **CI 覆盖严重偏窄**：CI 仅 `compileall` + 跑 ~6/68 个测试文件；回测因果、HSMM、storage、增量更新等核心测试**都不在 CI** → 核心逻辑回归不会被 CI 拦住 | `.github/workflows/ci.yml` | 中 |
| E2 | **依赖 hmmlearn 私有 API**：`filtered_predict_proba` 调 `model._compute_log_likelihood(x)`，多处用 `model.monitor_.history`/`.converged`；hmmlearn 升级改名即破坏因果概率链（配合 S5 无上界更脆弱） | `hmm_model.py:108`；`market_hmm.py:285-286` | 中 |
| E3 | **DuckDB 跨进程并发无保护**：`_DB_WRITE_LOCK` 仅进程内 `threading.RLock`；Streamlit 开着时再跑 CLI updater 写同一 `.duckdb` 可能 "database is locked" | `storage.py:19, 65-68` | 中（可用性） |
| E4 | **schema 迁移 `CREATE AS SELECT → DROP → RENAME`**：进程中途崩溃可能留下 `_migration` 表而原表已删 → 数据丢失风险（有文件锁 + `TransactionException` 重试缓解） | `storage.py:62-182, 1062-1178` | 低-中 |

---

## 6. 优先级建议

### P0（先做，性价比最高）

1. **修 HSMM 校准**：统一预测与实际的退出口径（都按 state_id 或都按 label，**H1**）；去掉校准训练集的 horizon 泄漏（**H2**）。这两点很可能让 verdict 从 `Invalid` 改善。
2. **强化 `validate_ohlcv` 并接入所有入库点**（**D1**）：补 `high>=low`、`low<=close<=high`、非负量、重复日期、巨缺口；个股/指数/基准/全A 路径统一调用。
3. **修正 `local_sample` 覆盖率口径**（**D2**）：用"本地样本数 / 全A 应有数"作分母，或在 UI 明示 local 模式不报覆盖率。

### P1

4. 自定义池改为"固定权重 + 停牌成员记 0 收益"或明确声明动态再平衡口径（**D3**）；低覆盖时拦截或强告警（**D8**）。
5. 统一回测 open/close 建仓日收益口径，避免净值对执行价选择敏感（**F1**）。
6. duration PMF 引入右删失处理、修 `age==max_duration` 的 `p_exit=1.0` 伪影（**H3/H4**）。
7. 给 `requirements.txt` 加上界；把 hmmlearn 私有 API 用法封装并加版本守卫（**S5 / E2**）。
8. 扩 CI：把回测因果、HSMM、storage、增量更新等核心测试纳入（**E1**）。

### P2

9. 涨跌停按板块/ST 分阈值、基于原始涨跌幅（**D4**）；多表增量加统一"目标交易日"闸门（**D5/D6**）。
10. `import_universe_json` 对导入字典做列名白名单校验（**S1**）；缓存改用更安全的序列化或校验来源（**S2**）；成分股抓取走 HTTPS（**S3**）。
11. `evaluate_forward_returns` 默认值改为强制带不可静默误用的标记（**F2**）。

---

## 7. 一句话总评

**架构和因果纪律是这个项目的强项**（前向滤波、walk-forward 缓存血缘、UI 概率门控都做得很认真，无高危未来函数）；**短板在"数据口径的诚实性"和"概率校准的正确性"**——而这恰恰是研究工具最该可信的地方。当前最该投入的是**修校准 + 补数据校验 + 修正覆盖率/指数口径**，而非堆新功能或做 HSMM UI。

---

## 附录 A：审计覆盖的主要文件

- 入口/配置：`app.py`、`src/config.py`、`src/utils/{runtime,dates,lineage,logging}.py`
- 数据源：`src/data_sources/{akshare_client,ths_helpers}.py`
- 数据层：`src/data_pipeline/{storage,updater,market_updater,universe,validators,calendar}.py`
- 特征：`src/features/{sector_features,market_features,stock_features,custom_basket_features,hsmm_features}.py`
- 模型：`src/models/{hmm_model,market_hmm,walk_forward,preprocessing,state_labeler,inference,hsmm_core,hsmm_model,hsmm_walk_forward,hsmm_labeler}.py`
- 评分/回测：`src/scoring/*`、`src/backtest/{sector_rotation,metrics}.py`
- 评估：`src/evaluation/{model_evaluation,hsmm_exit_calibration,hsmm_exit_targets,hsmm_diagnostics}.py`
- UI 门控：`src/ui/readiness_policy.py`、`src/ui/universe_manager.py` 等
- 工程：`.github/workflows/ci.yml`、`scripts/*.sh`、`*.command`、`requirements.txt`、`.gitignore`、`pyproject.toml`
- 文档交叉验证：`README.md`、`CHATGPT_PROGRAM_GUIDE.md`、`EVALUATION_README.md`、`OVERALL_EVALUATION_20260530.md`、`COMPLETION_AUDIT_20260529.md`

## 附录 B：方法与局限

- 本次为**静态只读审计**，未执行测试或运行应用（沙箱无依赖环境）。
- 因果性、缓存契约、门控策略、特征工程等关键结论由审计者直接通读源码确认；HSMM 内部数学、数据管道细节由专项审计交叉核对，均附 `文件:行号`。
- 严重度为审计者按"本地研究工具"威胁模型给出的相对判断，落地修复前建议结合实际数据复现验证。
