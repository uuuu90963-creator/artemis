#!/bin/bash
# Artemis Agent 一键安装脚本

set -e

ARTEMIS_DIR="$HOME/.hermes/artemis"
GITHUB_REPO="Artemis-agent/artemis"

echo "=================================================="
echo "  Artemis Agent 安装脚本"
echo "=================================================="

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.8+"
    exit 1
fi

# 检查 pip
if ! command -v pip &> /dev/null; then
    echo "[错误] 未找到 pip，请先安装"
    exit 1
fi

# 检查 git
if ! command -v git &> /dev/null; then
    echo "[错误] 未找到 git，请先安装"
    exit 1
fi

# 克隆或更新仓库
if [ -d "$ARTEMIS_DIR/.git" ]; then
    echo "[*] 检测到已有 Artemis，正在更新..."
    cd "$ARTEMIS_DIR"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null
else
    echo "[*] 正在克隆 Artemis 仓库..."
    mkdir -p "$(dirname "$ARTEMIS_DIR")"
    git clone "https://github.com/$GITHUB_REPO.git" "$ARTEMIS_DIR"
    cd "$ARTEMIS_DIR"
fi

# 安装依赖
echo "[*] 安装 Python 依赖..."
pip install -q rich pyyaml httpx python-dotenv

# 创建配置文件
if [ ! -f "$HOME/.hermes/.env" ]; then
    echo "[*] 创建配置文件 ~/.hermes/.env ..."
    mkdir -p "$HOME/.hermes"
    if [ -f "$ARTEMIS_DIR/.env.example" ]; then
        cp "$ARTEMIS_DIR/.env.example" "$HOME/.hermes/.env"
        echo ""
        echo "【重要】请编辑 ~/.hermes/.env 填入你的 API Key："
        echo "  - MINIMAX_API_KEY（必填）"
        echo "  - OPENROUTER_API_KEY（可选，建议填写以启用 vision）"
        echo ""
    fi
else
    echo "[*] 检测到已有 ~/.hermes/.env，保持不变"
fi

echo ""
echo "=================================================="
echo "  安装完成！"
echo "=================================================="
echo ""
echo "运行方式："
echo "  python3 $ARTEMIS_DIR/artemis.py"
echo ""
echo "首次使用请先编辑 ~/.hermes/.env 填入 API Key"
echo ""
