# Artemis 故障排查指南

## 目录
- [1. 启动失败](#1-启动失败)
- [2. LLM 对话无响应](#2-llm-对话无响应)
- [3. Telegram Bot 无法收发消息](#3-telegram-bot-无法收发消息)
- [4. Vision 图片分析不工作](#4-vision-图片分析不工作)
- [5. Skill 不生效](#5-skill-不生效)
- [6. 消息发送失败（Markdown 错误）](#6-消息发送失败markdown-错误)

---

## 1. 启动失败

### 症状
```
ModuleNotFoundError: No module named 'artemis'
```
**解决：**
```bash
cd ~/.hermes/artemis
export PYTHONPATH=/root/.hermes/artemis:$PYTHONPATH
python -c "from artemis import Artemis; a = Artemis(); a.initialize()"
```

### 症状
```
未设置 TELEGRAM_BOT_TOKEN
```
**解决：** 在 `~/.hermes/artemis/.env` 中添加：
```
TELEGRAM_BOT_TOKEN=your_token_here
```

### 症状
```
Artemis 已加载
⚠ 无法加载 Artemis: No API key configured
```
**原因：** 没有配置任何 LLM API Key。

**解决：** 在 `.env` 中至少配置一个 Provider 的 API Key：
```bash
MINIMAX_API_KEY=your_key   # 推荐，至少配置这个
OPENROUTER_API_KEY=your_key  # 备选，支持 vision
```

---

## 2. LLM 对话无响应

### 自检步骤
1. 发送 `/health` 命令查看 Provider 状态：
   - ✅ `minimax` — API 可用
   - ❌ `minimax No API key` — 未配置 Key
   - ❌ `minimax Timeout` — 网络问题或 API 宕机

2. 检查日志：
   ```bash
   tail -f ~/.hermes/artemis/logs/artemis.log
   ```

### 常见错误

#### `HTTP 401: Unauthorized`
**原因：** API Key 过期或无效。

#### `HTTP 429: Rate limit exceeded`
**原因：** 请求频率超限。Artemis 会自动重试（指数退避 3 次）。

#### `HTTP 400: Bad request`
**原因：** 模型名称错误或请求格式不兼容。Artemis 会尝试自动 fallback 到其他 Provider。

#### `Request timed out (after retries)`
**原因：** 网络延迟过高或 API 服务器响应慢。

**解决：** 检查网络：
```bash
ping api.minimaxi.com
curl -o /dev/null -s -w "%{http_code}" https://api.minimaxi.com/v1
```

---

## 3. Telegram Bot 无法收发消息

### Bot 收不到消息
1. 在 Telegram 中搜索 `@BotFather`，发送 `/mybots`
2. 确认 Bot 已启动（`python telegram_bot.py`）
3. 检查日志中是否有 `Processing update` 字样

### Bot 发送消息失败 `400 Bad Request`
**原因：** Markdown 格式错误。Artemis 会自动降级为纯文本发送。

**若仍失败：** 检查消息内容是否包含 Telegram 不支持的 HTML 字符。

### `Chat not found`
**原因：** Bot 被用户拉黑，或 Token 配置错误。

---

## 4. Vision 图片分析不工作

### 自检步骤
1. 发送 `/health` 查看 OpenRouter 状态
2. 或检查 Ollama 是否运行：
   ```bash
   curl http://localhost:11434/api/tags
   ```

### `Ollama vision not available`
**解决：** 安装并启动 Ollama vision 模型：
```bash
ollama pull llava
ollama run llava "describe this image"
```

### OpenRouter vision 失败
**原因：** 使用的模型不支持 vision。Artemis 会自动 fallback 到 Ollama（如果有）。

---

## 5. Skill 不生效

### 自检
发送 `/skills` 查看已加载的 Skill 列表。

### 启用的 Skill 不匹配
**原因：** Skill 的触发关键词可能和消息内容不匹配。

**解决：** 检查 `~/.hermes/skills/<skill-name>/SKILL.md` 中的 `trigger_keywords`。

### OpenClaw 工作区 Skill 未发现
**确认：** 检查 `WORKSPACE_DIR` 下的 `skills/` 目录是否存在且包含 `SKILL.md`。

---

## 6. 消息发送失败（Markdown 错误）

### 症状
```
Bad Request: can't parse entities: ...
```
**原因：** 消息内容包含无法识别的 Markdown 格式字符。

**解决：** Artemis v2.1+ 已内置 Markdown 降级机制，发送失败会自动重试纯文本。若仍有问题，检查日志中的具体报错内容。

---

## 健康检查命令

| 命令 | 作用 |
|------|------|
| `/health` | 测试所有 LLM Provider 连接状态 |
| `/skills` | 列出所有可用 Skill 及其状态 |
| `/model` | 查看当前模型和可用模型列表 |

## 日志位置

```
~/.hermes/artemis/logs/
├── artemis.log          # 主日志
├── evolution/           # 进化引擎日志
└── telegram_bot.log     # Telegram Bot 日志（如果有）
```

## 强制重启

```bash
# 停止运行中的 Bot
pkill -f telegram_bot.py
pkill -f artemis

# 重新启动
cd ~/.hermes/artemis
python telegram_bot.py
```
