# Artemis Agent

通用型 AI 助手框架，支持多模型、多通道视觉、大模型驱动自我进化。

## 特性

- **多模型路由**：MiniMax、OpenRouter (100+模型)、DeepSeek、Anthropic、Gemini
- **双通道视觉**：本地快速识别 + 云端深度理解
- **Function Call Agent**：ReAct 循环，工具调用自动化
- **自我进化引擎**：LLM 生成提案 → 安全审查 → Git 快照 → 自动测试 → 回滚保护
- **Cron 定时任务**：支持调度式后台任务
- **Telegram 机器人**：开箱即用的 Telegram 接入
- **MCP 插件系统**：可扩展的工具生态

## 快速开始

### 方式一：一键安装（推荐）

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Artemis-agent/artemis/main/install.sh)"
```

### 方式二：手动安装

```bash
# 克隆仓库
git clone https://github.com/Artemis-agent/artemis.git
cd artemis

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 运行
python3 artemis.py
```

## 配置

在 `~/.hermes/.env` 中配置：

```env
# 必填：MiniMax API（文本对话）
MINIMAX_API_KEY=your_minimax_key_here
MINIMAX_BASE_URL=https://api.minimaxi.com/v1

# 可选：OpenRouter API（支持 vision + tool calling）
OPENROUTER_API_KEY=your_openrouter_key_here

# 可选：Telegram Bot Token
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

## 项目结构

```
artemis/
├── artemis.py          # 主入口，CLI + TUI
├── agent.py            # Function Call Agent Loop
├── llm.py              # 多模型 LLM 客户端
├── vision.py           # 双通道视觉引擎
├── evolution_engine.py # 自我进化引擎
├── evolution/          # 进化子模块
│   ├── policy.py      # 安全策略白名单
│   ├── code_writer.py # 原子化代码写入
│   ├── self_tester.py # 自动测试
│   ├── rollback.py    # Git 快照回滚
│   └── proposer.py    # 进化提案生成
├── memory.py           # 记忆系统
├── router.py           # 模型路由
├── cron.py             # 定时任务
├── telegram_bot.py     # Telegram 接入
└── config.yaml         # 配置文件
```

## 交互模式

- **CLI/TUI**：直接运行 `python3 artemis.py` 进入彩色 TUI 界面
- **Telegram**：配置 `TELEGRAM_BOT_TOKEN` 后，Bot 模式自动激活
- **Cron**：通过 `/cron` 命令调度后台任务

## 进化系统

Artemis 内置大模型驱动的自我进化能力：

```
proposer.py (LLM生成) → policy.py (安全审查) → git snapshot → code_writer.py → self_tester.py → 验证通过?
                                                                                                                                   ↓
                                                                                                                            rollback.py
```

使用 `/propose <需求>` 发起进化提案，`/evolve` 执行完整进化流程。

## API 支持

| 模型 | 文本 | Vision | Tool Calling | 备注 |
|------|------|--------|-------------|------|
| MiniMax | ✅ | ❌ | ❌ | 主力文本模型 |
| OpenRouter | ✅ | ✅ | ✅ | 支持 100+ 模型 |
| DeepSeek | ✅ | ❌ | ❌ | |
| Anthropic | ✅ | ✅ | ✅ | |
| Gemini | ✅ | ✅ | ❌ | |

## 依赖

```
rich>=13.0
pyyaml>=6.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

## License

MIT
