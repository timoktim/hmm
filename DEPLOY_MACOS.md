# macOS 部署说明

这个包是源码部署包，适合在另一台 macOS 上解压后本地运行。它不会包含当前机器的虚拟环境、缓存、日志、DuckDB 数据库或模型文件。

## 环境要求

- macOS 12 或更高版本
- Python 3.11 或更高版本
- 能访问 Python 包源，用于首次安装依赖

如果目标机器没有 Python，建议先安装 Homebrew，然后执行：

```bash
brew install python@3.11
```

## 首次安装

解压后进入项目目录：

```bash
cd a_share_hmm_analyzer
./install_macos.command
```

也可以在 Finder 中双击 `install_macos.command`。

安装脚本会：

- 创建 `.venv`
- 安装 `requirements.txt`
- 创建 `data/cache`、`data/db`、`data/models`、`data/logs`
- 如果没有 `.env`，会从 `.env.example` 复制一份

## 启动网页

```bash
./run_macos.command
```

然后打开终端输出的 `Local URL`，通常是：

```text
http://localhost:8501
```

## 推荐运行顺序

先更新少量板块，确认数据源可用：

```bash
./update_industry.command 20200101 today 10
```

更新脚本默认使用增量模式；已有板块只回补最近 10 个自然日，避免每天从 20200101 全量重抓。`WORKERS=2` 或 `WORKERS=3` 可低并发抓取板块行情，但并发过高可能导致同花顺接口失败。

再训练模型：

```bash
./train_hmm.command 20200101 today 3
```

也可以在网页左侧完成同样操作。建议先不要勾选“同时更新成分股”，先把板块 HMM 跑通。

## 数据源说明

程序优先使用 AKShare 的同花顺 THS 板块接口：板块名称、板块指数行情和成分股都走同花顺路径。个股历史行情和市场基准使用腾讯接口，避免依赖东方财富接口。市场基准支持沪深300和中证全指。

数据源可能临时失效，请在网页的 `Data Health` 页面查看接口状态。

## 重要免责声明

本工具只用于研究分析，不构成投资建议。输出内容包括状态概率、风险标签、观察名单和回测结果，不用于自动下单。
