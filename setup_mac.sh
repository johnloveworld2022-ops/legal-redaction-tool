#!/bin/bash
# 一次性安装脚本。整个「法律脱敏工具」文件夹拷贝到新 Mac 的 $HOME 下之后,
# 在终端里运行一次: bash ~/法律脱敏工具/setup_mac.sh
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TOOL_DIR"

echo "== 1/5 检查 Homebrew =="
if ! command -v brew >/dev/null 2>&1; then
  echo "未安装 Homebrew,正在安装..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

echo "== 2/5 安装 Ollama 和 poppler =="
brew list ollama >/dev/null 2>&1 || brew install ollama
brew list poppler >/dev/null 2>&1 || brew install poppler

echo "== 3/5 启动 Ollama 并下载本地模型(约 4.7GB,请保持网络连接)=="
if ! pgrep -x ollama >/dev/null 2>&1; then
  nohup ollama serve > /tmp/ollama_serve.log 2>&1 &
  sleep 3
fi
ollama pull qwen2.5:7b-instruct

echo "== 4/5 创建 Python 虚拟环境并安装依赖 =="
if [ ! -d "$TOOL_DIR/venv" ]; then
  python3 -m venv "$TOOL_DIR/venv"
fi
source "$TOOL_DIR/venv/bin/activate"
pip install -q --upgrade pip
pip install -q ocrmac pillow cryptography pytest flask
# pypdf / python-docx are only used to build synthetic test fixtures
# (a composite PDF page, a docx with an embedded photo) -- not needed by
# the tool itself at runtime, only for the self-check below.
pip install -q pypdf python-docx

echo "== 5/5 自检:运行内置测试 =="
cd "$TOOL_DIR"
python -m pytest tests/ -q

echo ""
echo "安装完成。「打开脱敏工具」这个 App 在:"
echo "  $TOOL_DIR/apps/"
echo "建议把它拖到桌面或程序坞,方便使用。双击打开后会自动弹出浏览器网页。"
