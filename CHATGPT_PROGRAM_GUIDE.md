# 给 ChatGPT 的程序导览文档

本文用于辅助评估 `A股板块 HMM 分析器 vNext`。建议代码审阅或功能验收前先读本文，再进入具体文件。本文说明各部分代码作用、模块之间的逻辑关系、总体工作流，以及几个容易误判的数据语义点。

## 1. 系统定位

本程序是一个本地运行的 A 股投研辅助工具，不是自动交易系统。

核心目标是：

1. 抓取行业、概念、自定义股票池、个股、大盘指数和市场宽度数据。
2. 用 HMM 识别板块状态：`TrendUp / Neutral / RiskOff`。
3. 用独立的大盘 HMM 识别市场环境：`RiskOn / Neutral / RiskOff`。
4. 用 Universe Manager 限定观察范围，提高数据更新、训练、筛选和回测效率。
5. 用模型评估和 walk-forward 回测检查状态是否有实用区分度。
6. 用数据中心和可信度摘要告诉用户“当前结果能不能信”。

请不要把输出解释为买卖建议。模型状态、个股过滤和回测只用于研究。

## 2. 入口与页面路由

主入口是：

```text
app.py
```

`app.py` 做三件事：

1. 初始化数值线程限制：`src/utils/runtime.py`
2. 初始化 DuckDB schema：`DuckDBStorage().init_schema()`
3. 配置 Streamlit sidebar 与页面路由

当前 sidebar 按工作区组织页面：

```text
当前状态：总览、大盘状态
数据与质量：数据中心；数据健康为高级诊断入口，默认隐藏
板块和个股：板块池管理、板块详情、个股过滤；状态筛选器为高级研究入口，默认隐藏
模型实验：模型训练、模型评估、回测
```

需要高级入口时，在 sidebar 勾选“显示高级页面”。

重要语义：sidebar 里的“当前观察范围”可以选择：

```text
全市场（不使用板块池）
某个用户自定义板块池
```

如果选择全市场，页面和模型默认按全市场口径。只有明确选择板块池时，才按 Universe 口径计算覆盖率、run、状态、回测和筛选。

## 3. 数据库与持久化层

核心文件：

```text
src/data_pipeline/storage.py
```

该文件封装 DuckDB：

- 建表与迁移：`init_schema()`
- 通用 upsert：`upsert_df()`
- 通用查询：`read_df()`
- run 查找：`latest_run_id()`、`latest_run_for_current_scope()`、`get_model_run()`
- 数据健康：`update_health_success()`、`update_health_failure()`
- 失败记录：`record_fetch_failure()`、`clear_fetch_failure()`
- Universe 和自定义股票池 CRUD

主要表：

```text
sector_meta
sector_ohlcv
sector_constituents
stock_ohlcv
sector_features
sector_state_daily
model_runs
walk_forward_cache_runs
walk_forward_state_cache
market_index_ohlcv
market_benchmark_ohlcv
market_breadth_daily
market_regime_runs
market_regime_daily
all_a_stock_universe
user_universe
user_universe_items
custom_stock_basket
custom_stock_basket_members
custom_basket_ohlcv
data_health
fetch_failures
```

几个关键语义：

- `sector_features` 有 `feature_scope_id` / `feature_scope_type`，用于避免全市场和不同 Universe 的相对强弱、等权基准互相污染。
- `model_runs` 有 `universe_id` / `scope_type` / `include_custom_baskets` / `feature_scope_id`，页面选择 run 时应按当前 scope 查找。
- `market_breadth_daily` 主键是 `(trade_date, breadth_mode)`，同一天可以同时有 `local_sample` 和 `full_market` 两种宽度。
- `sector_meta.is_active` 用来区分当前数据源仍返回的板块和历史旧口径板块。覆盖率全市场分母应使用 active 板块。
- `data_health.stale_reads` 是历史累计次数，不等同于当前仍 stale。当前可信度摘要使用“当前 stale 接口数”和“历史 stale 次数”区分。

## 4. 数据源层

核心文件：

```text
src/data_sources/akshare_client.py
src/data_sources/ths_helpers.py
```

当前主数据源是 AKShare 封装的同花顺和腾讯接口。当前版本未接入 Tushare。

`AKShareClient` 负责：

- 行业 / 概念板块名称：`board_names()`
- 板块指数行情：`board_hist()`
- 板块成分股：`board_constituents()`
- 个股行情：`stock_hist()`
- 市场基准：`market_benchmark_hist()`
- 大盘指数：`market_index_hist()`
- 全 A 股票池：`all_a_stock_universe()`

该层同时做：

- 字段标准化
- 本地文件缓存
- TTL 判断
- 网络失败时使用 stale cache 兜底
- 写入 `data_health`

重要：`缓存命中` 是正常读有效缓存；`过期缓存` 是网络失败后用旧缓存兜底。后者会降低可信度，但历史累计值不应直接当作当前异常。

## 5. 数据更新层

核心文件：

```text
src/data_pipeline/updater.py
src/data_pipeline/market_updater.py
```

### 5.1 板块与个股更新

`src/data_pipeline/updater.py` 负责：

- `update_boards()`
- `incremental_update_boards()`
- `update_stock_histories()`
- `update_market_benchmark()`
- `update_universe_data()`

增量更新逻辑：

```text
如果本地已有 max_trade_date：
    从 max_trade_date - lookback_days 开始回补
否则：
    从用户输入 start_date 开始
```

低并发策略：

- 板块行情可以低并发，默认 1，建议不超过 3。
- 成分股和普通个股不默认大规模并发。

重要修复点：

- 更新板块池时，如果某个板块名不在当前 `board_names()` 返回列表中，会写入失败提示和 `fetch_failures`，不再静默跳过。
- 刷新板块名称时，当前数据源不再返回的旧板块会标记为 inactive，避免覆盖率把历史板块算进当前分母。

### 5.2 大盘与市场宽度更新

`src/data_pipeline/market_updater.py` 负责：

- `update_market_indices()`
- `update_market_breadth()`
- `update_all_a_stock_universe()`
- `update_all_a_stock_ohlcv()`
- `update_full_market_breadth()`

宽度模式：

```text
local_sample: 基于本地已有 stock_ohlcv 的样本宽度
full_market: 基于 all_a_stock_universe 的全 A 宽度
```

`market_breadth_daily` 中的覆盖字段：

```text
expected_count
effective_count
coverage_ratio
coverage_level
breadth_mode
```

`full_market` 只有在全 A 股票池存在，且覆盖率足够时才可解释为全市场宽度。否则 UI 应明确说明只是样本观察。

全 A 个股更新做了加速：

- 先探测数据源当前最新交易日。
- 如果某只股票本地已更新到该交易日，且启用“跳过已完成股票”，则跳过。
- 进度条显示总进度、阶段进度、当前股票、成功失败、跳过数量、缓存命中、已耗时和预计剩余。

## 6. Universe 与自定义股票池

核心文件：

```text
src/data_pipeline/universe.py
src/ui/universe_manager.py
src/features/custom_basket_features.py
```

Universe 是用户定义的观察范围，可以包含：

```text
industry
concept
custom_stock_basket
```

主要表：

```text
user_universe
user_universe_items
custom_stock_basket
custom_stock_basket_members
custom_basket_ohlcv
```

自定义股票池指数逻辑：

1. 读取成员股票行情。
2. 每只股票计算日收益。
3. 等权或自定义权重聚合日收益。
4. 从 1000 点起始复合成指数。
5. 写入 `custom_basket_ohlcv`。

注意：

- 停牌或缺失单只股票不会导致整个 basket 缺失。
- 如果有效成员数低于成员总数 50%，UI 应提示覆盖质量不足。
- 自定义股票池可以像板块指数一样参与 HMM、Dashboard、Backtest 和 Stock Filter。

## 7. 特征工程

核心文件：

```text
src/features/sector_features.py
src/features/market_features.py
src/features/stock_features.py
src/features/custom_basket_features.py
src/models/preprocessing.py
```

### 7.1 板块特征

`sector_features.py` 生成：

```text
ret_1d
ret_5d
ret_20d
vol_20d
amount_z_20d
rs_20d
drawdown_20d
ma20_slope
gap_1d
intraday_ret
limit_up_ratio
limit_down_ratio
suspended_or_missing_ratio
effective_member_count
amount_shock_z
```

相对强弱 `rs_20d` 的基准需要按当前 scope 计算，不能把全市场、Universe、自定义池混在一个特征语义里。

### 7.2 大盘特征

`market_features.py` 生成：

```text
hs300_ret_20d
zz500_ret_20d
zz1000_ret_20d
hs300_vol_20d
zz500_vol_20d
zz1000_vol_20d
hs300_drawdown_20d
zz1000_drawdown_20d
small_vs_large_20d
cross_index_dispersion_20d
up_ratio
above_ma20_ratio
amount_z_20d
```

如果市场宽度不达 full_market 标准，大盘 HMM 会自动降级为纯指数特征。

### 7.3 个股特征

`stock_features.py` 做个股级特征和 A 股结构标记：

```text
rs_vs_sector_20d
rs_vs_index_20d
amount_z_20d
vol_20d
drawdown_20d
is_limit_up
is_limit_down
is_one_word_limit
is_suspended_or_missing
gap_1d
intraday_ret
consecutive_limit_up_days
consecutive_limit_down_days
```

涨跌停判断是近似估计，暂未精确区分 ST、创业板、科创板、北交所涨跌幅限制。

## 8. HMM 模型层

核心文件：

```text
src/models/hmm_model.py
src/models/market_hmm.py
src/models/state_labeler.py
src/models/inference.py
src/models/walk_forward.py
```

### 8.1 板块 HMM

`train_hmm()` 训练板块模型：

1. 按全市场或 Universe 读取 sector-like OHLCV。
2. 构建 scope-aware 特征。
3. winsorize 和 scaler 只在训练窗口估计。
4. 训练 Gaussian HMM。
5. 根据状态样本统计自动标注 `TrendUp / Neutral / RiskOff`。
6. 写入 `model_runs` 和 `sector_state_daily`。

`sector_state_daily.state_source`：

```text
in_sample_display: 样本内展示状态，不能当作因果回测证据
causal_backtest: walk-forward 推断状态，可用于回测和有效性判断
```

### 8.2 walk-forward 回测状态

`walk_forward.py` 负责因果状态推断：

- 信号日只能使用截至该日的数据。
- 默认每月重训，而不是每天重训。
- 结果按参数缓存到 `walk_forward_state_cache`。

评估或回测如果选择 walk-forward 状态，必须读取 `walk_forward_state_cache`；没有缓存时不能退回样本内状态伪装因果结果。

### 8.3 大盘 HMM

`market_hmm.py` 训练独立大盘模型：

- 输出风险偏好、震荡、风险回避概率。
- 不直接预测指数涨跌。
- 如果全 A 宽度覆盖不足，则不用宽度，只用指数特征。
- 写入 `market_regime_runs` 和 `market_regime_daily`。

## 9. 评分与筛选

核心文件：

```text
src/scoring/sector_ranker.py
src/scoring/stock_filter.py
src/scoring/market_filter.py
```

### 9.1 板块评分

`sector_ranker.py` 依据状态概率、趋势特征、相对强弱等生成 `sector_score`。

`market_filter.py` 统一大盘状态 multiplier：

```text
RiskOn: 1.00
Neutral: 0.75
RiskOff: 0.40
```

当前大盘状态在主 UI 中更偏风险提示，不应误导为已完整接入所有回测结果。

### 9.2 个股过滤

`stock_filter.py` 做板块内成分股筛选：

1. 读取成分股或自定义股票池成员。
2. 读取个股行情。
3. 计算相对板块、相对市场基准、成交额、回撤和趋势。
4. 输出评分表、筛选漏斗、失败原因。

重要规则：

```text
close > ma20
ma20_slope > 0
rs_vs_sector_20d > 0
rs_vs_index_20d > 0
```

如果缺少市场基准，`rs_vs_index_20d` 不应硬算，也不应把它等同于相对板块强弱。

## 10. 回测与评估

核心文件：

```text
src/backtest/sector_rotation.py
src/backtest/metrics.py
src/evaluation/model_evaluation.py
src/ui/backtest_page.py
src/ui/model_evaluation_page.py
```

### 10.1 回测

回测策略：

```text
model: HMM TrendUp + sector_score
baseline_1_rs20_top_n: 20日相对强弱轮动
baseline_2_equal_weight: 全板块等权
```

关键边界：

- 不允许全历史一次性 `predict_proba` 后回测。
- 信号日 `t` 只能使用 `t` 及以前数据。
- 信号日 `t`，执行日 `t+1`。
- 默认单边交易成本 0.1%。
- 换仓成本按实际新增和减少仓位计算。

### 10.2 模型评估

`model_evaluation.py` 包含：

- 状态后未来收益分析。
- 策略对照分析。
- 状态稳定性分析。
- 数据质量摘要。

评估页必须区分：

```text
样本内状态评估
因果 walk-forward 状态评估
```

样本内状态只能看状态区分度，不能当成样本外有效性证据。

## 11. 状态筛选与板块周期研究

核心文件：

```text
src/analysis/sector_cycles.py
src/ui/state_screener_page.py
src/ui/sector_detail.py
src/ui/state_colors.py
```

`sector_cycles.py` 负责：

- 读取样本内或 walk-forward 状态。
- 把逐日状态压缩成连续状态段。
- 计算每段收益、最大回撤、持续天数、前后状态。
- 筛选状态切换。

状态筛选器用于发现值得研究的板块，不等于买入信号。

板块详情包含：

```text
状态总览
周期切换
个股叠加
成分股排名
```

颜色约定：

```text
TrendUp: 绿色
Neutral: 黄色
RiskOff: 橘色
```

个股叠加使用归一化净值比较相对强弱，不代表价格绝对水平。

## 12. UI 组件与中文化

核心文件：

```text
src/ui/components/data_status_bar.py
src/ui/components/data_trust_card.py
src/ui/components/data_coverage.py
src/ui/components/operation_result.py
src/ui/formatters.py
src/ui/help_texts.py
```

### 12.1 数据状态条

`data_status_bar.py` 在主要页面顶部展示：

- 当前数据状态。
- 最近网络成功。
- 当前 stale 接口数。
- 历史 stale 次数。
- 当前 run 范围。
- feature scope。
- 市场宽度口径。
- 大盘模型是否使用宽度。

注意：历史 stale 次数不应直接判定当前结果异常。

### 12.2 数据可信度卡片

`data_trust_card.py` 展示更详细的可信度摘要，默认放在 expander 里。

### 12.3 数据覆盖度

`data_coverage.py` 是数据中心首页的核心。它展示：

- 行业板块覆盖。
- 概念板块覆盖。
- 板块成分股覆盖。
- 个股行情覆盖。
- 全 A 股票池。
- 大盘指数。
- 市场宽度：本地样本 / 全 A。
- 市场基准。

全 A 宽度 UI 不直接显示内部枚举 `full_market / partial_sample`，而显示：

```text
全市场覆盖达标
样本覆盖不足
样本严重不足
本地样本观察
```

### 12.4 operation_result

`operation_result.py` 把更新结果压缩成一行摘要，详细日志放 expander，避免页面被 update summary 撑开。

## 13. 数据中心页面逻辑

核心文件：

```text
src/ui/data_center_page.py
```

页面分三 tab：

```text
数据概览
数据更新
更新日志
```

数据更新 tab 使用：

```text
任务选择 + 一个“开始更新”按钮
```

任务包括：

```text
更新当前板块池数据
更新全市场板块数据
更新当前板块池个股行情
更新全 A 宽度数据链路
更新大盘指数与市场基准
重试失败任务
```

日常用户不应在主流程看到：

- 手动输入股票代码。
- 更新数量限制。
- HMM 训练控件。

测试限制、force refresh、并发数等放在“高级参数”。

模型训练已移到：

```text
src/ui/model_training_page.py
```

## 14. 常见误解与评估时重点检查

### 14.1 `90/119` 行业覆盖

如果看到这种情况，要检查 `sector_meta.is_active`。当前有效行业应只统计 active 板块。历史旧板块不应进入全市场分母。

### 14.2 `stale_reads = 3239`

这是历史累计过期缓存读取次数，不代表当前仍有 3239 个过期缓存。当前状态应看“当前 stale 接口数”。

### 14.3 `full_market` 和 `partial_sample`

这些是内部枚举，不应直接出现在面向用户的 metric 里。UI 应显示中文解释。

### 14.4 样本内状态与 walk-forward 状态

样本内状态可以用于观察模型如何划分状态，但不能作为样本外有效性证据。回测和有效性评估应优先使用 walk-forward 缓存。

### 14.5 全 A 宽度与本地样本宽度

本地样本宽度只反映本地已有个股行情，不代表全 A。只有 full_market 覆盖达标时，才可作为大盘 HMM 宽度输入。

## 15. 评估建议

推荐先运行：

```bash
.venv/bin/python -m pytest -q -m "not slow"
.venv/bin/python -m pytest -q -m slow
```

重点测试文件：

```text
tests/test_strategy_validity.py
tests/test_market_regime.py
tests/test_universe.py
tests/test_vnext_convergence.py
tests/test_vnext_ui_a_share.py
tests/test_vnext_state_screener.py
tests/test_data_center_refactor.py
tests/test_incremental_updates.py
```

人工评估建议按这个顺序：

1. 数据中心：看覆盖率、当前口径、宽度解释、更新任务。
2. 板块池管理：创建 Universe，添加行业/概念/自定义股票池。
3. 模型训练：训练全市场或当前 Universe 的板块 HMM。
4. 总览：检查当前 run 是否与 scope 对齐。
5. 状态筛选器：检查样本内与 walk-forward 来源是否明确。
6. 板块详情：检查状态段、周期切换和个股叠加。
7. 模型评估：检查状态后收益和对照策略是否因果。
8. 回测：检查执行日、交易成本和对照策略。
9. 大盘状态：检查宽度是否 full_market，是否实际用于模型。

## 16. 包含与不包含

评估包通常包含：

```text
源码
测试
README
EVALUATION_README
安装和运行脚本
本导览文档
```

评估包不包含：

```text
.venv
data/db
data/cache
data/models
data/logs
旧 zip 包
```

因此首次运行需要重新安装依赖、更新数据并训练模型。
