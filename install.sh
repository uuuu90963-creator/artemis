#!/bin/bash
# Artemis Agent 一键安装脚本
# 支持交互式选择模型

set -e

ARTEMIS_DIR="$HOME/.hermes/artemis"
GITHUB_REPO="uuuu90963-creator/artemis"
ENV_FILE="$HOME/.hermes/.env"

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
pip install -q rich pyyaml httpx

# 创建必要目录
mkdir -p "$HOME/.hermes/artemis/memories"
mkdir -p "$HOME/.hermes/artemis/logs"
mkdir -p "$HOME/.hermes/artemis/cache"

# ==================== 交互式模型选择 ====================
echo ""
echo "=================================================="
echo "  选择你的 AI 模型"
echo "=================================================="
echo ""
echo "  1) MiniMax (免费，文字对话，推荐国内用户)"
echo "     - abab6.5s-chat (快速)"
echo "     - abab6.5-chat (平衡)"
echo ""
echo "  2) OpenRouter (支持 vision + tool calling，按量计费)"
echo "     - gpt-4o-mini (快速便宜)"
echo "     - gpt-4o (更强)"
echo "     - claude-3-haiku (性价比)"
echo ""
echo "  3) DeepSeek (编程能力强)"
echo "     - deepseek-chat"
echo "     - deepseek-coder"
echo ""
echo "  4) Anthropic Claude (最强推理)"
echo "     - claude-3-sonnet-4 (平衡)"
echo "     - claude-3-5-haiku (快速)"
echo ""
echo "  5) Google Gemini (多模态)"
echo "     - gemini-2.0-flash (推荐)"
echo "     - gemini-1.5-pro"
echo ""
echo "=================================================="
echo ""

read -p "请选择文本模型类型 [1-5，默认1]: " model_choice
model_choice="${model_choice:-1}"

# 根据选择设置模型
case $model_choice in
    1)
        TEXT_PROVIDER="minimax"
        TEXT_MODEL="abab6.5s-chat"
        ;;
    2)
        TEXT_PROVIDER="openrouter"
        TEXT_MODEL="openai/gpt-4o-mini"
        ;;
    3)
        TEXT_PROVIDER="deepseek"
        TEXT_MODEL="deepseek-chat"
        ;;
    4)
        TEXT_PROVIDER="anthropic"
        TEXT_MODEL="claude-3-sonnet-4-20250514"
        ;;
    5)
        TEXT_PROVIDER="google"
        TEXT_MODEL="gemini-2.0-flash"
        ;;
    *)
        TEXT_PROVIDER="minimax"
        TEXT_MODEL="abab6.5s-chat"
        ;;
esac

echo ""
echo "[*] 文本模型: $TEXT_PROVIDER / $TEXT_MODEL"

# Vision 模型选择
VISION_PROVIDER="openrouter"
VISION_MODEL="openai/gpt-4o-mini"

if [ "$TEXT_PROVIDER" = "openrouter" ] || [ "$TEXT_PROVIDER" = "anthropic" ] || [ "$TEXT_PROVIDER" = "google" ]; then
    echo ""
    read -p "是否使用与文本相同的 provider 处理 vision？[Y/n]: " same_vision
    if [ "$same_vision" = "n" ] || [ "$same_vision" = "N" ]; then
        echo ""
        echo "  vision 模型选项："
        echo "  1) OpenRouter - gpt-4o-mini (推荐，便宜)"
        echo "  2) OpenRouter - gpt-4o (更强)"
        echo "  3) Anthropic Claude - claude-3-sonnet (最强)"
        echo ""
        read -p "请选择 vision 模型 [1-3，默认1]: " vision_choice
        vision_choice="${vision_choice:-1}"
        case $vision_choice in
            1) VISION_MODEL="openai/gpt-4o-mini" ;;
            2) VISION_MODEL="openai/gpt-4o" ;;
            3) VISION_MODEL="anthropic/claude-3-sonnet-4-20250514"; VISION_PROVIDER="openrouter" ;;
            *) VISION_MODEL="openai/gpt-4o-mini" ;;
        esac
    else
        VISION_PROVIDER="$TEXT_PROVIDER"
        VISION_MODEL="$TEXT_MODEL"
    fi
fi

echo "[*] Vision 模型: $VISION_PROVIDER / $VISION_MODEL"
echo ""

# ==================== API Key 输入 ====================
echo "=================================================="
echo "  配置 API Key"
echo "=================================================="
echo ""

MINIMAX_KEY=""
OPENROUTER_KEY=""
ANTHROPIC_KEY=""
DEEPSEEK_KEY=""
GOOGLE_KEY=""
TELEGRAM_TOKEN=""
ALLOWED_USERS=""

read -p "请输入 MiniMax API Key（必填）: " MINIMAX_KEY
MINIMAX_KEY="${MINIMAX_KEY:-}"

if [ "$TEXT_PROVIDER" = "openrouter" ] || [ "$VISION_PROVIDER" = "openrouter" ]; then
    read -p "请输入 OpenRouter API Key: " OPENROUTER_KEY
    OPENROUTER_KEY="${OPENROUTER_KEY:-}"
fi

if [ "$TEXT_PROVIDER" = "anthropic" ]; then
    read -p "请输入 Anthropic API Key: " ANTHROPIC_KEY
    ANTHROPIC_KEY="${ANTHROPIC_KEY:-}"
fi

if [ "$TEXT_PROVIDER" = "deepseek" ]; then
    read -p "请输入 DeepSeek API Key: " DEEPSEEK_KEY
    DEEPSEEK_KEY="${DEEPSEEK_KEY:-}"
fi

if [ "$TEXT_PROVIDER" = "google" ]; then
    read -p "请输入 Google API Key: " GOOGLE_KEY
    GOOGLE_KEY="${GOOGLE_KEY:-}"
fi

echo ""
read -p "请输入 Telegram Bot Token（可选，回车跳过）: " TELEGRAM_TOKEN
TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-}"
if [ -n "$TELEGRAM_TOKEN" ]; then
    read -p "允许的 Telegram 用户 ID（多个用逗号分隔，可选）: " ALLOWED_USERS
fi

# ==================== 写入配置文件 ====================
echo ""
echo "[*] 写入配置文件..."

# 创建 .env
cat > "$ENV_FILE" << ENVEOF
# Artemis 配置文件
# 由 install.sh 自动生成

# MiniMax API
MINIMAX_API_KEY=${MINIMAX_KEY}
MINIMAX_BASE_URL=https://api.minimaxi.com/v1

# OpenRouter API（vision + tool calling）
OPENROUTER_API_KEY=${OPENROUTER_KEY}

# Anthropic API
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}

# DeepSeek API
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}

# Google API
GOOGLE_API_KEY=${GOOGLE_KEY}

# Telegram Bot
TELEGRAM_BOT_TOKEN=${TELEGRAM_TOKEN}
TELEGRAM_ALLOWED_USERS=${ALLOWED_USERS}
ENVEOF

# 创建 config.yaml（新格式，带 schema 版本）
cat > "$ARTEMIS_DIR/config.yaml" << CONFIGEOF
# Artemis 配置（Schema v1）
_schema_version: 1

model:
  text: "${TEXT_PROVIDER}:${TEXT_MODEL}"
  vision: "${VISION_PROVIDER}:${VISION_MODEL}"
  reasoning: "openrouter:openai/gpt-4o-mini"

routing:
  text_default: "${TEXT_PROVIDER}"
  vision_primary: "${VISION_PROVIDER}"
  vision_fallback: "local"

tools:
  enabled_toolsets:
    - file
    - memory
    - web
  disabled_tools: []
  max_file_size_mb: 10
  terminal_timeout: 60

memory:
  db_path: "~/.hermes/artemis/memories/memory.db"
  max_memories: 10000
  similarity_threshold: 0.01

telegram:
  enabled: false
  allowed_users: []
  reply_to_message: true
  streaming: false

agent:
  max_turns: 20
  max_tokens_per_message: 500
  context_window: 128000
  auto_save: true

security:
  approve_all: false
  block_high_danger: true
  dangerous_commands_log: "~/.hermes/artemis/logs/commands.log"

display:
  show_cost: true
  show_provider: true
  show_thinking: false
CONFIGEOF

# 设置安全权限
chmod 600 "$ENV_FILE"
chmod 600 "$ARTEMIS_DIR/config.yaml"

# ==================== 安装 CLI ====================
echo ""
echo "[*] 安装 CLI 入口..."

# 创建 ~/.local/bin 目录（如果没有）
mkdir -p "$HOME/.local/bin"

# 创建 CLI 软链接
ln -sf "$ARTEMIS_DIR/artemis_cli.py" "$HOME/.local/bin/artemis"
chmod +x "$ARTEMIS_DIR/artemis_cli.py"

# 检查 PATH
if [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
    echo "[*] ~/.local/bin 已在 PATH 中"
else
    echo "[!] 请将 ~/.local/bin 添加到 PATH:"
    echo "    echo 'export PATH=\$HOME/.local/bin:\$PATH' >> ~/.bashrc"
fi

echo ""
echo "=================================================="
echo "  安装完成！"
echo "=================================================="
echo ""
echo "运行方式："
echo "  artemis                    # 交互式聊天（推荐）"
echo "  artemis run '任务描述'      # 单次任务"
echo "  artemis tools              # 查看工具"
echo "  artemis status             # 查看状态"
echo "  artemis setup              # 重新配置"
echo ""
echo "CLI 命令已安装到: ~/.local/bin/artemis"
echo ""
echo "配置文件："
echo "  ~/.hermes/.env             # API Keys"
echo "  $ARTEMIS_DIR/config.yaml   # 系统配置"
echo ""
