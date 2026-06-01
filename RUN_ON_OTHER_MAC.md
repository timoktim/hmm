# 在另一台 Mac 上运行

本包不包含本机虚拟环境、缓存、数据库或模型产物。解压后按下面步骤运行即可。

## 1. 准备 Python

建议安装 Python 3.11 或 3.12。

如果已经有 Python，可以在终端检查：

```bash
python3 --version
```

## 2. 安装依赖

进入解压后的目录，运行：

```bash
./install_macos.command
```

这个脚本会创建 `.venv`，安装 `requirements.txt` 中的依赖，并创建 `data/cache`、`data/db`、`data/models`、`data/logs` 目录。

## 3. 启动网页

```bash
./run_macos.command
```

启动后打开：

```text
http://localhost:8501
```

如果 8501 已被其他程序占用，可以临时运行：

```bash
PORT=8502 ./run_macos.command
```

## 4. 常用命令

更新少量行业板块数据：

```bash
./update_industry.command 20200101 today 10
```

更新少量概念板块数据：

```bash
./update_concept.command 20200101 today 10
```

这两个脚本默认使用增量更新，并从本地最新交易日往前回补 10 个自然日。需要低并发加速时可以临时设置：

```bash
WORKERS=2 ./update_industry.command 20200101 today 30
```

训练 HMM：

```bash
./train_hmm.command 20200101 today 3
```

## 5. 注意

- 第一次安装依赖需要联网。
- 程序通过 AKShare 调用同花顺板块接口和腾讯行情接口；可在应用内 `Data Health` 页面查看失败原因、缓存状态和失败重抓入口。
- `Stock Filter` 页面可更新沪深300或中证全指市场基准；缺少市场基准时会跳过 `rs_vs_index_20d` 评分项并明确提示。
- 这是研究分析工具，不会自动下单，也不构成投资建议。
