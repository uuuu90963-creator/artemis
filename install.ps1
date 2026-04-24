#!/usr/bin/env pwsh
# Artemis Agent - Windows 一键安装脚本

param(
    [switch]$SkipOllama,
    [switch]$SkipDocker
)

$ARTEMIS_DIR = "$HOME\.hermes\artemis"
$ENV_FILE = "$HOME\.hermes\.env"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Artemis Agent 安装脚本 (Windows)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Python
Write-Host "[*] 检查 Python..." -ForegroundColor Yellow
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    Write-Host "[错误] 未找到 Python，请先从 https://python.org 下载安装 Python 3.8+" -ForegroundColor Red
    Write-Host "  安装时请勾选 'Add Python to PATH'" -ForegroundColor Yellow
    exit 1
}
$pythonVersion = & python --version 2>&1
Write-Host "[OK] 找到 $pythonVersion" -ForegroundColor Green

# 检查 pip
Write-Host "[*] 检查 pip..." -ForegroundColor Yellow
try {
    $pipVersion = & python -m pip --version 2>&1
    Write-Host "[OK] pip 可用" -ForegroundColor Green
} catch {
    Write-Host "[错误] pip 不可用，请重新安装 Python" -ForegroundColor Red
    exit 1
}

# 检查/创建 .hermes 目录
Write-Host "[*] 准备目录..." -ForegroundColor Yellow
$hermesDir = Split-Path $ENV_FILE
if (-not (Test-Path $hermesDir)) {
    New-Item -ItemType Directory -Path $hermesDir -Force | Out-Null
}
if (-not (Test-Path $ARTEMIS_DIR)) {
    Write-Host "[*] 正在克隆 Artemis 仓库..." -ForegroundColor Yellow
    git clone https://github.com/Artemis-agent/artemis.git $ARTEMIS_DIR
} else {
    Write-Host "[*] 检测到已有 Artemis 目录" -ForegroundColor Cyan
    Write-Host "[*] 如需更新，请手动运行: cd $ARTEMIS_DIR; git pull" -ForegroundColor Cyan
}

# 安装 Python 依赖
Write-Host "[*] 安装 Python 依赖..." -ForegroundColor Yellow
Set-Location $ARTEMIS_DIR
& python -m pip install --quiet rich pyyaml httpx python-dotenv
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 依赖安装失败" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] 依赖安装完成" -ForegroundColor Green

# 创建配置文件
if (-not (Test-Path $ENV_FILE)) {
    Write-Host "[*] 创建配置文件..." -ForegroundColor Yellow
    @"
# Artemis Agent 配置文件
# 请填入你的 API Key

# 必填：MiniMax API（文本对话）
MINIMAX_API_KEY=your_minimax_key_here

# 可选：OpenRouter API（支持 vision + tool calling，推荐）
OPENROUTER_API_KEY=your_openrouter_key_here

# 可选：DeepSeek API
DEEPSEEK_API_KEY=

# 可选：Anthropic API
ANTHROPIC_API_KEY=

# 可选：Google Gemini API
GEMINI_API_KEY=

# 可选：Telegram Bot Token
TELEGRAM_BOT_TOKEN=

# 可选：Ollama 本地视觉（如果有）
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_VISION_MODEL=llava:7b
"@ | Out-File -FilePath $ENV_FILE -Encoding UTF8
    Write-Host "[OK] 配置文件已创建: $ENV_FILE" -ForegroundColor Green
    Write-Host ""
    Write-Host "【重要】请编辑 $ENV_FILE 填入你的 API Key！" -ForegroundColor Magenta
} else {
    Write-Host "[*] 检测到已有配置文件，保持不变" -ForegroundColor Cyan
}

# 检查 Ollama（可选）
if (-not $SkipOllama) {
    Write-Host "[*] 检查 Ollama..." -ForegroundColor Yellow
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollama) {
        Write-Host "[OK] Ollama 已安装" -ForegroundColor Green
        Write-Host "    如需安装视觉模型，运行: ollama pull llava:7b" -ForegroundColor Cyan
    } else {
        Write-Host "[*] Ollama 未检测到（可选，跳过）" -ForegroundColor Cyan
        Write-Host "    如需本地视觉能力，从 https://ollama.com 下载安装" -ForegroundColor Cyan
        Write-Host "    安装后运行: ollama pull llava:7b" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "运行方式：" -ForegroundColor White
Write-Host "  python $ARTEMIS_DIR\artemis.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "或使用 Docker（推荐）：" -ForegroundColor White
Write-Host "  cd $ARTEMIS_DIR" -ForegroundColor Yellow
Write-Host "  docker-compose up -d" -ForegroundColor Yellow
Write-Host ""
