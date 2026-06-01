#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

find_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    echo "$PYTHON_BIN"
    return 0
  fi
  for candidate in python3.11 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

PY="$(find_python)" || {
  echo "未找到 Python 3.11+。请先安装 Python，例如：brew install python@3.11"
  exit 1
}

"$PY" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11 或更高版本")
if sys.version_info >= (3, 13):
    print("警告：hmmlearn/AKShare/Streamlit 在 Python 3.13 及以上版本可能不稳定，建议使用 Python 3.11 或 3.12。")
print(f"Python OK: {sys.version.split()[0]}")
PY

echo "创建虚拟环境..."
"$PY" -m venv .venv

echo "安装依赖..."
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p data/cache data/db data/models data/logs
if [[ ! -f .env ]]; then
  cp .env.example .env
fi

echo
echo "安装完成。运行 ./run_macos.command 启动网页。"
