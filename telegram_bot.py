#!/usr/bin/env python3
"""
Artemis Telegram Bot - Telegram 平台接入
使用 httpx 直接调用 Telegram Bot API，长轮询方式
"""

import os
import sys
import json
import asyncio
import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import httpx
import dotenv

# 基础路径（必须在 LOG_DIR 之前定义）
BASE_DIR = Path.home() / ".hermes" / "artemis"
CACHE_DIR = BASE_DIR / "cache" / "images"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ===== 日志配置（必须在 BASE_DIR 之后） =====
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "telegram_bot.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("artemis.telegram")

# 加载环境变量（手动解析 .env 文件）
ENV_PATH = Path.home() / ".hermes" / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# 获取 Token（懒加载，不存在时返回空）
def _get_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")

TELEGRAM_BOT_TOKEN = _get_token()
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/" if TELEGRAM_BOT_TOKEN else ""

# 允许的用户 ID（可选的访问控制）
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "")
if ALLOWED_USERS:
    ALLOWED_USERS = set(int(uid) for uid in ALLOWED_USERS.split(",") if uid.strip())
else:
    ALLOWED_USERS = None

class ConversationDB:
    """对话历史数据库"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库（带 WAL 模式提升并发性能）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # 启用 WAL 模式：写操作不阻塞读操作
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")  # 平衡性能和安全
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                image_path TEXT,
                message_id INTEGER
            )
        """)
        # 索引：按 chat_id 查历史，按 timestamp 排序
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_id ON conversations(chat_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON conversations(timestamp)")
        # 复合索引：常用查询优化
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_time ON conversations(chat_id, timestamp DESC)")
        conn.commit()
        conn.close()
    
    def add_message(self, chat_id: int, role: str, content: str,
                    image_path: Optional[str] = None, message_id: Optional[int] = None):
        """添加消息"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO conversations (chat_id, role, content, image_path, message_id)
                VALUES (?, ?, ?, ?, ?)
            """, (chat_id, role, content, image_path, message_id))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"[Telegram Bot] 数据库写入错误: {e}")

    def get_history(self, chat_id: int, limit: int = 20) -> List[Dict]:
        """获取对话历史"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                SELECT role, content, timestamp, image_path
                FROM conversations
                WHERE chat_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (chat_id, limit))
            rows = c.fetchall()
            conn.close()
            return [{"role": r[0], "content": r[1], "timestamp": r[2], "image_path": r[3]}
                    for r in reversed(rows)]
        except sqlite3.Error as e:
            print(f"[Telegram Bot] 数据库读取错误: {e}")
            return []

    def clear_history(self, chat_id: int):
        """清空对话历史"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM conversations WHERE chat_id = ?", (chat_id,))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"[Telegram Bot] 数据库清空错误: {e}")

    def count(self, chat_id: int) -> int:
        """统计消息数"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM conversations WHERE chat_id = ?", (chat_id,))
            count = c.fetchone()[0]
            conn.close()
            return count
        except sqlite3.Error as e:
            print(f"[Telegram Bot] 数据库统计错误: {e}")
            return 0


class ArtemisTelegramBot:
    """Artemis Telegram 机器人"""
    
    def __init__(self, agent=None):
        self.agent = agent
        self.token = TELEGRAM_BOT_TOKEN
        self.api_url = TELEGRAM_API_URL
        self.offset = 0
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # 对话历史数据库
        db_path = BASE_DIR / "memories" / "conversations.db"
        self.db = ConversationDB(db_path)
        
        # 用户状态（当前模型等）
        self.user_states: Dict[int, Dict[str, Any]] = {}
        
        # 命令列表（用于 BotCommand menu）
        self.commands = [
            ("start", "开始使用"),
            ("help", "帮助信息"),
            ("reset", "重置会话"),
            ("skills", "查看技能"),
            ("model", "切换模型"),
            ("vision", "图片分析"),
        ]
    
    def _is_allowed(self, chat_id: int) -> bool:
        """检查用户是否被允许"""
        if ALLOWED_USERS is None:
            return True
        return chat_id in ALLOWED_USERS
    
    async def _make_request(self, method: str, **params) -> Dict:
        """发送 API 请求"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.api_url}{method}", json=params)
            response.raise_for_status()
            return response.json()
    
    def _sync_make_request(self, method: str, **params) -> Dict:
        """同步发送 API 请求（用于线程池）"""
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{self.api_url}{method}", json=params)
            response.raise_for_status()
            return response.json()
    
    async def send_message(self, chat_id: int, text: str,
                          parse_mode: str = "Markdown",
                          reply_to_message_id: Optional[int] = None) -> Dict:
        """发送消息"""
        # 清理 MiniMax 返回的<think>标签
        import re
        cleaned_text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        if not cleaned_text:
            cleaned_text = "(无实质内容)"

        # Telegram Markdown 对 <> 敏感，先转义
        escaped_text = cleaned_text.replace("<", "＜").replace(">", "＞")

        params = {
            "chat_id": chat_id,
            "text": escaped_text,
            "parse_mode": parse_mode,
        }
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id
        return await self._make_request("sendMessage", **params)
    
    async def send_photo(self, chat_id: int, photo: str, caption: Optional[str] = None,
                        parse_mode: str = "Markdown") -> Dict:
        """发送图片"""
        params = {
            "chat_id": chat_id,
            "photo": photo,
        }
        if caption:
            params["caption"] = caption
            params["parse_mode"] = parse_mode
        return await self._make_request("sendPhoto", **params)
    
    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None):
        """回应回调查询"""
        params = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = text
        return await self._make_request("answerCallbackQuery", **params)
    
    def download_file(self, file_path: str, dest_path: Path) -> Path:
        """下载文件"""
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        with httpx.Client(timeout=60.0) as client:
            response = client.get(url)
            response.raise_for_status()
            dest_path.write_bytes(response.content)
        return dest_path
    
    async def get_file(self, file_id: str) -> Optional[str]:
        """获取文件路径"""
        result = await self._make_request("getFile", file_id=file_id)
        if result.get("ok"):
            return result["result"]["file_path"]
        return None
    
    def get_user_state(self, chat_id: int) -> Dict[str, Any]:
        """获取用户状态"""
        if chat_id not in self.user_states:
            self.user_states[chat_id] = {
                "model": "minimax",
                "waiting_for_vision": False,
            }
        return self.user_states[chat_id]
    
    def set_user_model(self, chat_id: int, model: str):
        """设置用户模型"""
        state = self.get_user_state(chat_id)
        state["model"] = model
    
    async def handle_command(self, chat_id: int, command: str, args: str, 
                            message_id: int) -> Optional[str]:
        """处理命令"""
        command = command.lower().strip("/")
        
        if command == "start":
            # 启动时异步检查升级（不阻塞欢迎语）
            asyncio.create_task(self.notify_upgrade_if_available(chat_id))
            return self.cmd_start(chat_id)
        elif command == "help":
            return self.cmd_help()
        elif command == "reset":
            self.db.clear_history(chat_id)
            return "✅ 对话历史已清空，让我们重新开始吧！"
        elif command == "skills":
            return await self.cmd_skills()
        elif command == "model":
            return self.cmd_model(args)
        elif command == "vision":
            state = self.get_user_state(chat_id)
            state["waiting_for_vision"] = True
            return "📷 请发送一张图片，我会帮你分析。"
        elif command == "upgrade":
            return await self.cmd_upgrade(args)
        elif command == "artemis":
            # /artemis 开头的消息，后面内容当普通消息处理
            return None  # 交给普通消息处理
        else:
            return f"未知命令: /{command}\n\n发送 /help 查看可用命令。"
    
    def cmd_start(self, chat_id: int) -> str:
        """欢迎语"""
        return """
🤖 **Artemis Agent** - 您好！

我是 Artemis，一个温暖的 AI 助手。

**可用命令：**
• `/start` - 显示此欢迎信息
• `/help` - 获取帮助
• `/reset` - 重置对话历史
• `/skills` - 查看可用技能
• `/model <name>` - 切换模型 (minimax/openrouter/deepseek)
• `/vision` - 分析图片
• `/upgrade` - 检查/执行版本升级

**使用方式：**
• 直接发送消息与我对话
• 发送 `/artemis <内容>` 触发处理
• 回复图片进行视觉分析

有什么我可以帮您的吗？ 🌟
""".strip()
    
    def cmd_help(self) -> str:
        """帮助信息"""
        return """
📖 **帮助信息**

**基础命令：**
• `/start` - 欢迎语
• `/help` - 显示此帮助
• `/reset` - 清空对话历史

**高级功能：**
• `/model <name>` - 切换 AI 模型
  支持: `minimax`, `openrouter`, `deepseek`
 
• `/vision` - 进入图片分析模式
  发送图片后会自动分析
 
• `/skills` - 查看已安装的技能

• `/upgrade` - 检查/执行版本升级
  `/upgrade` - 查看是否有新版本
  `/upgrade now` - 执行升级

**对话：**
• 直接发送文字开始对话
• 使用 `/artemis` 前缀触发处理
• 回复图片进行视觉分析

有什么问题随时问我！ 😊
""".strip()
    
    async def cmd_skills(self) -> str:
        """列出技能"""
        if self.agent:
            skills = self.agent.list_skills()
        else:
            skills = []
        
        if not skills:
            return "📦 **可用技能**\n\n暂无安装技能。使用 `/help` 查看更多功能。"
        
        skills_list = "\n".join(f"  • `{s}`" for s in skills)
        return f"📦 **已安装技能**\n\n{skills_list}\n\n使用技能请直接描述需求，我会自动调度。"
    
    def cmd_model(self, args: str) -> str:
        """切换模型"""
        args = args.strip().lower()
        
        valid_models = ["minimax", "openrouter", "deepseek"]
        
        if not args:
            current = self.get_user_state(0).get("model", "minimax")
            return f"🔄 **当前模型**: `{current}`\n\n可选: {', '.join(valid_models)}\n\n用法: `/model <name>`"
        
        if args not in valid_models:
            return f"❌ 未知模型: `{args}`\n\n可选: {', '.join(valid_models)}"
        
        # 注意：这里只是记录用户偏好，实际模型切换需要 agent 支持
        return f"✅ 已切换到 `{args}` 模型\n\n(模型切换功能需要后端支持)"
    
    async def cmd_upgrade(self, args: str) -> str:
        """升级命令"""
        # 动态导入避免循环依赖
        try:
            from upgrader import UpgradeChecker, format_telegram_upgrade_message
        except ImportError:
            return "⚠️ 升级模块不可用，请重新安装 Artemis。"

        # 检查是否在 bot 配置中开启了自动升级通知
        config = getattr(self, 'config', {}) or {}
        upgrade_cfg = config.get("upgrade", {})
        checker = UpgradeChecker({
            "auto_upgrade": upgrade_cfg.get("auto_upgrade", False),
            "silent": False,  # 用户主动触发，不静默
        })

        if args.strip().lower() == "now":
            # 执行升级
            result = checker.upgrade()
            if result["success"]:
                return f"🚀 升级成功！\n\n新版本: `{result['new_version']}`\n{result['message']}"
            else:
                return f"❌ 升级失败:\n{result['message']}"

        # 检查新版本
        check_result = checker.check()
        if not check_result["has_update"]:
            if check_result.get("auto_upgraded"):
                return f"✅ {check_result['message']}"
            return f"✅ 当前已是最新版本: `{check_result['current_version']}`"

        # 有新版本，显示通知
        msg = format_telegram_upgrade_message(check_result)
        return msg

    async def notify_upgrade_if_available(self, chat_id: int) -> None:
        """
        启动时检查并推送升级通知（非阻塞）
        只通知一次，避免重复打扰用户
        """
        try:
            from upgrader import UpgradeChecker
        except ImportError:
            return

        config = getattr(self, 'config', {}) or {}
        upgrade_cfg = config.get("upgrade", {})
        if not upgrade_cfg.get("notify_on_startup", True):
            return

        checker = UpgradeChecker({
            "auto_upgrade": upgrade_cfg.get("auto_upgrade", False),
            "silent": True,  # 静默检查，不自动升级
        })
        result = checker.check()

        if result["has_update"] and result["message"]:
            await self.send_message(chat_id, result["message"])
        elif result.get("auto_upgraded"):
            await self.send_message(
                chat_id,
                f"🚀 已自动升级到新版本: `{result['latest_version']}`"
            )
        # 没有更新时不做任何提示，避免噪音

    async def process_message(self, chat_id: int, text: str, 
                              message_id: int, photo: Optional[str] = None,
                              file_path: Optional[str] = None) -> str:
        """处理普通消息"""
        # 保存用户消息
        self.db.add_message(chat_id, "user", text, file_path, message_id)
        
        # 调用 Artemis 处理
        if self.agent:
            try:
                if file_path:
                    response = self.agent.chat(text, image=file_path)
                else:
                    response = self.agent.chat(text)
            except Exception as e:
                response = f"处理消息时出错: {str(e)}"
        else:
            response = f"[模拟响应] 收到: {text[:50]}..."
        
        # 保存助手回复
        self.db.add_message(chat_id, "assistant", response, message_id=message_id)
        
        return response
    
    async def handle_update(self, update: Dict):
        """处理 Telegram 更新"""
        # 跳过无效更新
        if "message" not in update and "edited_message" not in update:
            return
        
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            return
        
        # 检查权限
        if not self._is_allowed(chat_id):
            await self.send_message(chat_id, "❌ 您没有权限使用此机器人。")
            return
        
        # 获取消息内容
        text = message.get("text", "")
        photo = message.get("photo")
        message_id = message.get("message_id")
        
        # 检查是否是命令
        if text.startswith("/"):
            parts = text.split(" ", 1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            
            # 特殊处理 /artemis 命令
            if command == "/artemis":
                user_text = args
                if not user_text.strip():
                    await self.send_message(chat_id, "请输入内容，例如: `/artemis 你好`")
                    return
                response = await self.process_message(chat_id, user_text, message_id)
            else:
                # 其他命令
                response = await self.handle_command(chat_id, command, args, message_id)
                if response is None:
                    # 命令未处理，当作普通消息
                    response = await self.process_message(chat_id, text, message_id)
        else:
            # 检查是否在等待图片
            state = self.get_user_state(chat_id)
            if state.get("waiting_for_vision") and photo:
                state["waiting_for_vision"] = False
                # 下载并处理图片
                response = await self.handle_photo(chat_id, photo, text, message_id)
            elif photo:
                # 有图片但没在 vision 模式
                response = await self.handle_photo(chat_id, photo, text, message_id)
            elif text.strip():
                # 普通文字消息
                response = await self.process_message(chat_id, text, message_id)
            else:
                return
        
        # 发送响应
        if response:
            try:
                await self.send_message(chat_id, response, reply_to_message_id=message_id)
            except Exception as e:
                print(f"[Telegram Bot] 发送消息失败: {e}")
                await self.send_message(chat_id, f"发送失败: {str(e)[:100]}")
    
    async def handle_photo(self, chat_id: int, photos: List, caption: str, 
                          message_id: int) -> str:
        """处理图片消息"""
        if not photos:
            return "未收到图片"
        
        # 获取最大尺寸的图片
        photo = photos[-1]
        file_id = photo.get("file_id")
        
        if not file_id:
            return "无法获取图片"
        
        # 下载图片
        try:
            file_path = await self.get_file(file_id)
            if not file_path:
                return "无法获取文件路径"
            
            # 生成保存路径
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = CACHE_DIR / f"{chat_id}_{timestamp}.jpg"
            
            # 在线程池中下载
            loop = asyncio.get_event_loop()
            saved_path = await loop.run_in_executor(
                self.executor, self.download_file, file_path, dest_path
            )
            
            # 处理图片
            if self.agent:
                response = self.agent.chat(caption or "请分析这张图片", image=str(saved_path))
            else:
                response = f"[模拟] 已收到图片: {saved_path.name}"
            
            return response
            
        except Exception as e:
            return f"处理图片失败: {str(e)}"
    
    async def get_updates(self) -> List[Dict]:
        """获取更新（长轮询）"""
        try:
            result = await self._make_request(
                "getUpdates",
                offset=self.offset,
                timeout=30,
                allowed_updates=["message", "edited_message", "callback_query"]
            )
            if result.get("ok"):
                return result.get("result", [])
            return []
        except Exception as e:
            print(f"[Telegram Bot] getUpdates 错误: {e}")
            return []
    
    async def set_commands(self):
        """设置 Bot Commands"""
        commands = [
            {"command": cmd, "description": desc} 
            for cmd, desc in self.commands
        ]
        try:
            await self._make_request("setMyCommands", commands=commands)
            print("[Telegram Bot] ✓ 命令菜单已设置")
        except Exception as e:
            print(f"[Telegram Bot] 设置命令菜单失败: {e}")
    
    async def start(self):
        """启动机器人"""
        print(f"[Telegram Bot] 🚀 启动中...")
        print(f"[Telegram Bot] Token: {self.token[:10]}...")
        
        # 设置命令菜单
        await self.set_commands()
        
        print("[Telegram Bot] 📡 开始长轮询...")
        print("[Telegram Bot] 按 Ctrl+C 停止\n")
        
        while True:
            updates = await self.get_updates()
            
            for update in updates:
                self.offset = max(self.offset, update["update_id"] + 1)
                try:
                    await self.handle_update(update)
                except Exception as e:
                    print(f"[Telegram Bot] 处理更新失败: {e}")
            
            # 稍微休眠避免过于频繁
            if not updates:
                await asyncio.sleep(0.5)


class TelegramBotRunner:
    """ Telegram Bot 运行器 """
    
    def __init__(self, agent=None):
        self.agent = agent
        self.bot = ArtemisTelegramBot(agent)
    
    async def run(self):
        """运行 bot """
        await self.bot.start()
    
    def run_sync(self):
        """同步运行（用于直接执行）"""
        asyncio.run(self.bot.start())


# ==================== 主入口 ====================

def main():
    """主入口"""
    print("=" * 50)
    print(" Artemis Telegram Bot ")
    print("=" * 50)

    # 检查 Token
    if not TELEGRAM_BOT_TOKEN:
        print("[错误] 未设置 TELEGRAM_BOT_TOKEN")
        print("请在 ~/.hermes/.env 中添加: TELEGRAM_BOT_TOKEN=your_token_here")
        sys.exit(1)

    # 尝试导入 Artemis
    agent = None
    try:
        sys.path.insert(0, str(BASE_DIR))
        from artemis import Artemis
        agent = Artemis()
        agent.initialize()
        print(f"[Telegram Bot] ✓ Artemis 已加载")
    except Exception as e:
        print(f"[Telegram Bot] ⚠ 无法加载 Artemis: {e}")
        print("[Telegram Bot] 以模拟模式运行")
    
    # 启动 Bot
    bot = ArtemisTelegramBot(agent)
    
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\n[Telegram Bot] 已停止")


if __name__ == "__main__":
    main()
