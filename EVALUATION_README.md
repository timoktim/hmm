# A股板块 HMM 分析器 vNext 评估说明

本评估包用于代码审阅、功能验收和本地复现。包内包含源码、测试、依赖清单、macOS 安装/运行脚本和说明文档；不包含本机虚拟环境、数据库、缓存、模型文件或运行日志。

如需让 ChatGPT 或其他代码评估工具快速理解程序结构，请先阅读：

```text
CHATGPT_PROGRAM_GUIDE.md
```

## 快速运行

建议使用 Python 3.11 或 3.12。

```bash
./install_macos.command
PORT=8502 ./run_macos.command
```

打开：

```text
http://localhost:8502
```

## 推荐评估命令

```bash
.venv/bin/python -m pytest -q -m "not slow"
.venv/bin/python -m pytest -q -m slow
```

如尚未安装依赖，请先运行：

```bash
./install_macos.command
```

## 本版重点

- HSMM 生命周期模型旁路：新增 `DiscreteDurationGaussianHSMM`、checkpoint 训练、逐交易日 daily snapshot、因果 prefix Viterbi、HSMM 落库表和诊断报告。HSMM 不替换 HMM，不参与交易排序，只用于状态持续时间、状态阶段、退出概率和下一状态诊断。
- 信号有效性验证：新增 `src/evaluation/signal_validation.py`，按因果 walk-forward、下一交易日开盘执行、随机基线、成本敏感性和状态后收益进行验证。当前主结论为 Weak，不应把 HMM 轮动策略解释为已稳定有效。
- vNext 收敛迭代：减少 sidebar 噪音，新增数据中心、模型评估页和统一结果可信度摘要。
- 特征作用域隔离：`sector_features` 新增 `feature_scope_id` / `feature_scope_type`，避免全市场与不同 Universe 的相对强弱特征互相污染。
- Universe 因果缓存修复：walk-forward 回测缓存现在使用与训练一致的 `feature_scope_id`，并会持久化对应 scope 的特征，避免评估和 Dashboard 串用错误作用域。
- 模型评估：支持状态后未来收益分析、状态稳定性分析、HMM/RS20/等权策略对照入口和数据质量说明。
- 模型评估 / 状态筛选器缓存口径：walk-forward 缓存按当前范围过滤，全市场不再误选小 Universe 缓存。
- 数据中心：重构为“数据概览 / 数据更新 / 更新日志”，用“任务选择 + 一个开始按钮”替代多个并列更新入口。
- 数据覆盖可视化：显示行业、概念、成分股、个股、全 A 股票池、大盘指数、市场宽度和市场基准覆盖情况。
- 更新进度修复：勾选“同时更新成分股”时，进度条会覆盖“板块行情 + 成分股”两个阶段。
- Universe Manager：支持行业板块、概念板块和自定义股票池组成观察范围。
- 状态筛选器：支持按状态切换筛选板块，并联动板块详情周期研究。
- 因果 walk-forward 回测：避免完整历史一次性状态推断造成未来函数。
- 大盘状态 HMM：独立识别风险偏好、中性震荡、风险回避环境。
- 市场宽度 / 本地样本宽度：支持同一天并存 `local_sample` 和 `full_market`，UI 优先按最新交易日显示当前口径。
- Stock Filter：支持市场基准相对强弱、自定义股票池成员评分和透明筛选说明。
- Data Health：展示网络成功、失败、缓存命中、过期缓存读取和个股缺失情况。

## 最新验收结果

最近一次本地验收：

```bash
.venv/bin/python -m pytest -q -m "not slow"
# 125 passed, 2 deselected

.venv/bin/python -m pytest -q -m slow
# 2 passed, 125 deselected
```

专项 HSMM 验收：

```bash
.venv/bin/python -m pytest -q tests/test_hsmm_model.py tests/test_hsmm_storage.py tests/test_hsmm_walk_forward.py tests/test_hsmm_diagnostics.py
# 10 passed
```

真实数据 HSMM P0 smoke run：

```text
run_id: hsmm_lifecycle_p0_smoke_20260530
reports/hsmm_diagnostics/hsmm_lifecycle_p0_smoke_20260530/summary.md
```

该 run 因果审计通过，daily snapshot 覆盖 7884 行 / 17 个交易日 / 464 个板块，但退出概率校准缺少基本单调性，verdict 为 `InvalidDueToCalibrationFailure`。因此目前不建议进入 HSMM UI 展示阶段。

信号有效性验证报告：

```text
reports/signal_validation/primary_20260529_main/summary.md
```

主结论：`Weak`。因果审计通过，但 HMM 策略在默认 0.1% 单边成本下未能优于 RS20 和全板块等权，随机基线也不支持策略层面的强有效性判断。

当前数据库快照曾验证：

- 行业板块行情：90/90
- 概念板块行情：375/375
- 板块成分股：465/465
- 个股行情：5207/5522
- 全 A 市场宽度：4620/5522，覆盖约 83.7%，达 full_market 口径
- 本地样本宽度：仍单独标记为本地样本，不与全 A 宽度混用

## 评估注意

- 本工具为研究分析用途，不自动下单，也不构成投资建议。
- 数据源依赖 AKShare 封装的同花顺、腾讯等接口，上游接口可能变动。
- “本地样本宽度”只代表本地已有个股行情；只有 `breadth_mode = full_market` 且覆盖达标时，才可作为全 A 市场宽度理解。
- 大盘状态目前只作为风险提示；回测页中未展示尚未因果接入的过滤开关。
- `data/db`、`data/cache`、`data/models`、`data/logs` 不在评估包内；首次运行需要自行更新数据并训练模型。
- HSMM 第一版是 Viterbi-EM MVP，诊断结论应优先看退出概率校准、下一状态预测和 churn reduction，不应用收益直接命名 Buy/Sell/RiskOff。若 diagnostics verdict 不是 `ValidLifecycleSignal` 或至少 `PartialLifecycleSignal`，不要把 HSMM 接入主 UI 或策略解释。
