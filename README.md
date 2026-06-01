# A股板块 HMM 状态分析器

本项目是一个本地运行的投研辅助工具，用于抓取 A 股行业/概念板块和自定义股票池数据，训练板块 Hidden Markov Model，并输出状态概率、风险标签、观察名单、模型评估和因果 walk-forward 回测结果。

它不会自动下单，也不提供交易指令。本工具只用于研究分析，不构成投资建议。

## 安装

建议使用 Python 3.11。

```bash
cd a_share_hmm_analyzer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

当前主路径使用 AKShare 封装的同花顺和腾讯接口。

## 数据源

主数据源为 AKShare 封装的同花顺和腾讯接口，不再优先使用东方财富：

- 同花顺：行业/概念板块名称、板块指数行情、板块成分股
- 腾讯：A 股个股日线行情、沪深300和中证全指市场基准

接口可能因上游变化失效。应用内 `Data Health` 页面会展示最近成功时间、失败原因、缓存命中和过期缓存读取情况。

## 更新数据

```bash
python -m src.data_pipeline.updater --board-type industry --start 20200101 --end today --incremental --lookback-days 10 --workers 1
python -m src.data_pipeline.updater --board-type concept --start 20200101 --end today --incremental --lookback-days 10 --workers 1
```

默认建议使用增量更新：已有板块会从本地最大交易日往前回补 10 个自然日，只有缺失板块才从输入起点开始。调试时可以加 `--limit 10`，先抓取少量板块；`--workers` 只并发板块行情，建议不超过 3。

## 系统工作原理

系统由三层组成：

1. 大盘状态 HMM：识别整体市场环境，输出风险偏好、中性震荡、风险回避。它是风险提示器，不直接预测指数涨跌。
2. 板块 HMM：对行业、概念和自定义股票池指数进行状态识别，输出趋势上行、中性震荡、风险回避。
3. 个股过滤：在指定板块或股票池内，根据趋势、相对强弱、回撤和成交额等规则筛选候选股，并展示筛选漏斗。

Universe Manager 可把行业、概念和自定义股票池组成观察范围。板块特征包含 `feature_scope_id`，避免全市场和不同 Universe 的等权基准、相对强弱特征互相污染。

## 训练模型

```bash
python -m src.models.hmm_model --train-start 20200101 --train-end today --states 3
```

模型使用所有板块的时间序列联合训练，并通过 `lengths` 保留不同板块边界。HMM 训练后再根据状态样本的收益、相对强弱、波动率和回撤自动标注 `TrendUp`、`Neutral`、`RiskOff`。
完整板块 HMM 默认使用 `min_covar=1e-4` 抑制方差坍缩，并用 3 次不同随机种子初始化后选择最终似然最高的一次；可通过 `--n-init` 和 `--random-state` 调整。

## HSMM 生命周期模型

HSMM 是旁路研究模型，不替换现有 HMM，也不参与交易排序。它回答的是状态生命周期问题：当前状态已经持续多久、处在 early/mature/late 哪个阶段、未来 1/3/5/10 天退出当前状态的概率、退出后最可能进入哪个状态。

第一版实现为 `DiscreteDurationGaussianHSMM`：离散时长、对角高斯发射分布、semi-Markov Viterbi segmentation 和 Viterbi-EM。训练特征来自历史行情和相对收益，不包含 future/forward return。

小范围运行示例：

```bash
python -m src.models.hsmm_walk_forward \
  --db data/db/a_share_hmm.duckdb \
  --start-date 2026-03-01 \
  --end-date today \
  --n-states 4 \
  --max-duration 40 \
  --train-window-days 252 \
  --train-frequency every_n_trade_days \
  --train-every-n-trade-days 20 \
  --snapshot-frequency daily \
  --n-iter 10 \
  --run-id hsmm_smoke_test

python -m src.evaluation.hsmm_diagnostics \
  --db data/db/a_share_hmm.duckdb \
  --run-id hsmm_smoke_test \
  --horizons 1,3,5,10,20 \
  --output reports/hsmm_diagnostics/hsmm_smoke_test
```

诊断报告的主结论不看交易收益，而看因果性审计、退出概率校准、下一状态预测、状态持续时间和跳变控制。HSMM 的 `p_exit` 不是下跌概率，也不是上涨概率。`snapshot_frequency=daily` 时，状态快照按交易日逐日输出；诊断中的 1/3/5/10/20 日 horizon 均按交易日行数解释，不按自然日解释。

## 打开网页

```bash
streamlit run app.py
```

页面按工作区组织：

- 当前状态：总览、大盘状态。
- 数据与质量：数据中心；数据健康属于高级诊断入口，默认隐藏。
- 板块和个股：板块池管理、板块详情、个股过滤；状态筛选器属于高级研究入口，默认隐藏。
- 模型实验：模型训练、模型评估、回测。

侧边栏可开启“显示高级页面”，用于查看数据健康和状态筛选器等诊断/研究入口。

## 如何解读模型评估

模型评估页不是为了证明“明天会涨”，而是检查状态是否对未来收益分布有区分度，以及 HMM 策略相对简单 RS20 轮动和等权基准是否有增益。重点看：

- TrendUp / Neutral / RiskOff 后未来 5 日、20 日收益是否有明显差异。
- HMM 策略和对照策略是否使用相同 Universe。
- 回测是否为因果 walk-forward。
- 扣费后指标是否仍优于简单基准。
- 数据可信度摘要是否提示 stale cache、scope 不一致或样本宽度不足。

## 市场宽度限制

当前“市场宽度 / 本地样本宽度”默认由本地 `stock_ohlcv` 中已有个股行情聚合而来。只有 `coverage_level = full_market` 时才可按全市场宽度理解；否则它只代表本地已抓取股票样本，不代表全 A 市场。若覆盖不足，大盘 HMM 会自动降级为纯指数特征。

## 回测边界

回测信号日 `t` 只使用截至 `t` 的状态和特征，默认每月重训 HMM，并把 walk-forward 状态按参数缓存到 DuckDB。训练样本内状态只作为非因果展示，不作为策略回测默认输入。

执行日为下一交易日。默认按下一交易日开盘成交，收益从该日开盘到收盘开始计算；如选择收盘成交，则收益从后续交易日开始。回测同时输出扣费前和扣费后结果，默认单边交易成本为 0.1%。

## 当前未正式启用的功能

- 自动交易：未实现，也不会自动下单。
- 全市场股票池宽度更新：接口保留在代码层，但正常 UI 不暴露可点击入口。
- 大盘状态过滤接入回测：当前只作为风险提示，不影响回测结果。
- Tushare 深度集成：未接入当前版本。
- `stock_scores` 持久化评分追踪：已从主流程和新库默认 schema 移除；个股过滤采用即时计算结果。

## 目录结构

```text
a_share_hmm_analyzer/
  app.py
  requirements.txt
  README.md
  .env.example
  data/
    cache/
    db/
  src/
    data_sources/
    data_pipeline/
    features/
    models/
    scoring/
    backtest/
    ui/
    utils/
  tests/
```
