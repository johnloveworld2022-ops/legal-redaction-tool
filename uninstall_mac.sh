#!/bin/bash
# 完全卸载脚本。会删除:工具本身、她处理过的所有案件数据、每个案件的
# 加密密钥、以及 Ollama 和已下载的本地模型。删除后无法恢复,运行前
# 请确认这就是你要的结果。
#
# 用法:在她的 Mac 上打开终端,运行:
#   bash ~/法律脱敏工具/uninstall_mac.sh

set -uo pipefail

TOOL_DIR="$HOME/法律脱敏工具"
WORKBENCH_DIR="$HOME/法律脱敏工作台"

echo "即将删除:"
echo "  1. 工具本身: $TOOL_DIR"
echo "  2. 全部案件数据: $WORKBENCH_DIR"
echo "  3. 每个案件在钥匙串里的加密密钥"
echo "  4. Ollama 本体和已下载的本地模型(约 4.7GB)"
echo ""
read -p "确认要继续吗?输入 yes 继续,其他任意键取消: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "已取消,什么都没删除。"
  exit 0
fi

echo ""
echo "== 1/5 停止正在运行的脱敏工具网页服务 =="
pkill -f "gui/app.py" 2>/dev/null || true

echo "== 2/5 清理每个案件在钥匙串里的加密密钥 =="
if [ -d "$WORKBENCH_DIR" ]; then
  for case_dir in "$WORKBENCH_DIR"/案件_*; do
    [ -d "$case_dir" ] || continue
    case_folder_name="$(basename "$case_dir")"
    security delete-generic-password -s "法律脱敏工具-${case_folder_name}" -a "mapping-key" 2>/dev/null \
      && echo "  已删除:${case_folder_name} 的密钥" \
      || echo "  跳过(没找到或已删除):${case_folder_name}"
  done
else
  echo "  没有案件数据文件夹,跳过。"
fi

echo "== 3/5 删除案件数据文件夹 =="
rm -rf "$WORKBENCH_DIR"

echo "== 4/5 删除工具本身(含虚拟环境、源代码、App)=="
rm -rf "$TOOL_DIR"

echo "== 5/5 卸载 Ollama 和本地模型 =="
if command -v ollama >/dev/null 2>&1; then
  pkill -x ollama 2>/dev/null || true
  brew uninstall ollama 2>/dev/null || echo "  (brew uninstall ollama 失败,可能不是 brew 装的,请手动检查)"
fi
# brew uninstall 不会清理已下载的模型数据,模型单独存在这里:
rm -rf "$HOME/.ollama"

echo ""
echo "卸载完成。"
echo ""
echo "没有动的东西(这些一般是其他软件也会用到的通用组件,不建议因为"
echo "卸载这一个工具就删掉):Homebrew 本身、poppler。如果确定完全不需要"
echo "了,可以自己运行 'brew uninstall poppler'。"
echo ""
echo "如果桌面或程序坞上还留着「打开脱敏工具」的图标,那只是一个快捷方式,"
echo "手动拖进废纸篓即可。"
