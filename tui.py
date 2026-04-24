import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, List, Dict, Any

# 优先用 Rich 库，如果没装则用纯ANSI
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

BASE_DIR = Path.home() / ".hermes" / "artemis"

class ArtemisTUI:
    """Artemis 终端图形界面"""

    def __init__(self, agent: "Artemis"):
        self.agent = agent
        self.console = Console() if HAS_RICH else None
        self.running = False
        self.history: List[Dict] = []  # 对话历史
        self.page = 0
        self.page_size = 20
        self.input_mode = "chat"  # "chat" | "command"

    # ======== 输出 ========

    def print_banner(self):
        """打印 Banner"""
        banner = """
╔══════════════════════════════════════════════╗
║     ✦  Artemis  ·  AI 助手  ·  v0.1.0       ║
║        感知优先  ·  好奇进化  ·  温暖专业      ║
╚══════════════════════════════════════════════╝
"""
        if HAS_RICH:
            self.console.print(banner, style="bold cyan")
        else:
            print(banner)

    def print_welcome(self):
        """欢迎信息"""
        lines = [
            "👋 欢迎使用 Artemis！",
            "",
            "命令模式（以 / 开头）：",
            "  /chat          切换到聊天模式",
            "  /model <name>  切换模型 (minimax/openrouter/deepseek/anthropic)",
            "  /skills        查看可用技能",
            "  /cron          查看定时任务",
            "  /addcron       添加定时任务",
            "  /history       查看对话历史",
            "  /memory        搜索记忆",
            "  /clear         清屏",
            "  /exit          退出",
            "",
            "快捷键：Ctrl+C 退出，↑↓ 翻页，Tab 补全命令",
        ]
        for line in lines:
            self._println(line)

    def _println(self, text: str, style: str = ""):
        """打印一行"""
        if HAS_RICH:
            self.console.print(text, style=style)
        else:
            # 纯ANSI fallback
            if style == "bold":
                text = f"\033[1m{text}\033[0m"
            elif style == "cyan":
                text = f"\033[36m{text}\033[0m"
            elif style == "green":
                text = f"\033[32m{text}\033[0m"
            elif style == "yellow":
                text = f"\033[33m{text}\033[0m"
            elif style == "red":
                text = f"\033[31m{text}\033[0m"
            elif "dim" in style:
                text = f"\033[2m{text}\033[0m"
            print(text)

    def print_message(self, role: str, content: str, timestamp: str = None):
        """打印消息"""
        ts = timestamp or datetime.now().strftime("%H:%M")
        if role == "user":
            prefix = f"👤 [{ts}] 你"
            self._println(f"\n{prefix}:", "bold")
            self._println(f"   {content}", "dim")
        elif role == "assistant":
            prefix = f"🤖 [{ts}] Artemis"
            self._println(f"\n{prefix}:", "bold cyan")
            if HAS_RICH:
                self.console.print(Markdown(content))
            else:
                self._println(f"   {content}")
        elif role == "system":
            self._println(f"\n📋 [{ts}] 系统: {content}", "yellow")

    def print_error(self, text: str):
        self._println(f"\n❌ 错误: {text}", "red")

    def print_success(self, text: str):
        self._println(f"\n✅ {text}", "green")

    def print_info(self, text: str):
        self._println(f"\nℹ️  {text}", "cyan")

    # ======== 表格输出 ========

    def print_skills_table(self, skills: List[Dict]):
        """打印技能列表"""
        if HAS_RICH:
            table = Table(title="🎯 可用技能")
            table.add_column("名称", style="cyan")
            table.add_column("描述")
            table.add_column("触发词")
            table.add_column("状态", justify="center")
            for s in skills:
                status = "✅" if s.get("enabled", True) else "⛔"
                triggers = ", ".join(s.get("trigger_keywords", [])[:3])
                table.add_row(s["name"], s.get("description", ""), triggers, status)
            self.console.print(table)
        else:
            self._println("\n🎯 可用技能：", "bold")
            for s in skills:
                status = "✅" if s.get("enabled", True) else "⛔"
                self._println(f"  {status} {s['name']}: {s.get('description', '')}")

    def print_cron_table(self, jobs: List[Dict]):
        """打印定时任务列表"""
        if HAS_RICH:
            table = Table(title="⏰ 定时任务")
            table.add_column("名称", style="cyan")
            table.add_column("计划", style="yellow")
            table.add_column("下次执行")
            table.add_column("状态", justify="center")
            table.add_column("执行次数", justify="right")
            for j in jobs:
                status = "🟢" if j.get("enabled") else "🔴"
                table.add_row(
                    j.get("name", j["job_id"]),
                    j.get("schedule", ""),
                    j.get("next_run", "—"),
                    status,
                    str(j.get("run_count", 0))
                )
            self.console.print(table)
        else:
            self._println("\n⏰ 定时任务：", "bold")
            for j in jobs:
                status = "🟢" if j.get("enabled") else "🔴"
                self._println(f"  {status} {j.get('name', j['job_id'])} | {j.get('schedule')} | 下次: {j.get('next_run', '—')}")

    def print_model_status(self, current: str, available: List[str]):
        """打印模型状态"""
        if HAS_RICH:
            table = Table(title="🤖 当前模型", show_header=False)
            table.add_column("项目", style="cyan")
            table.add_column("值")
            table.add_row("当前", f"[bold]{current}[/bold]")
            table.add_row("可用", ", ".join(available))
            self.console.print(table)
        else:
            self._println(f"\n🤖 当前模型: {current}", "bold")
            self._println(f"   可用: {', '.join(available)}")

    # ======== Spinner ========

    def show_spinner(self, text: str) -> Callable:
        """
        显示加载动画
        返回 stop 函数
        """
        if HAS_RICH:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
                auto_refresh=True
            )
            task = progress.add_task(text, total=None)
            progress.start()
            def stop():
                progress.stop()
            return stop
        else:
            # 简单动画
            chars = "|/-\\"
            self._println(f"\n⏳ {text}", "yellow")
            stop_event = threading.Event()
            def spin():
                i = 0
                while not stop_event.is_set():
                    sys.stdout.write(f"\r⏳ {text}... {chars[i%4]}")
                    sys.stdout.flush()
                    time.sleep(0.1)
                    i += 1
                sys.stdout.write("\r" + " " * 50 + "\r")
            t = threading.Thread(target=spin, daemon=True)
            t.start()
            def stop():
                stop_event.set()
                t.join(timeout=1)
            return stop

    # ======== 分页 ========

    def show_history_page(self, page: int):
        """显示历史分页"""
        start = page * self.page_size
        end = start + self.page_size
        page_history = self.history[start:end]

        self._println(f"\n📖 对话历史 (第 {page+1} 页)", "bold")
        for msg in reversed(page_history):
            self.print_message(msg["role"], msg["content"][:200], msg.get("timestamp"))

        total_pages = (len(self.history) + self.page_size - 1) // self.page_size
        self._println(f"\n第 {page+1}/{total_pages} 页 | ↑↓ 翻页 | q 退出", "dim")

    def paginate_input(self) -> str:
        """分页浏览历史，按 q 退出"""
        self.page = max(0, (len(self.history) - 1) // self.page_size)
        while True:
            os.system('stty raw -echo 2>/dev/null') if os.name == 'posix' else None
            try:
                import tty, termios
                key = sys.stdin.read(1)
            except:
                key = 'q'
            finally:
                os.system('stty -raw echo 2>/dev/null') if os.name == 'posix' else None

            if key == 'q' or key == 'Q':
                break
            elif key == '\x1b':  # ESC
                break
            self.show_history_page(self.page)

    # ======== 命令处理 ========

    def handle_command(self, cmd: str) -> bool:
        """
        处理命令
        返回 True 表示退出 TUI
        """
        cmd = cmd.strip()
        if cmd == "/exit" or cmd == "/quit":
            self._println("👋 再见！", "bold")
            return True
        elif cmd == "/clear":
            os.system("clear" if os.name != "nt" else "cls")
            self.print_banner()
        elif cmd == "/chat":
            self._println("切换到聊天模式，输入消息即可对话", "cyan")
        elif cmd == "/help":
            self.print_welcome()
        elif cmd == "/skills":
            from skills.skill_manager import SkillManager
            sm = SkillManager(BASE_DIR / "skills")
            skills = sm.list_skills()
            self.print_skills_table(skills)
        elif cmd == "/model":
            self._println(f"当前模型: {self.agent.current_provider}", "bold")
            self._println(f"可用模型: {self.agent.llm.get_available_providers()}")
        elif cmd.startswith("/model "):
            new_model = cmd[7:].strip()
            if self.agent.set_provider(new_model):
                self.print_success(f"已切换到 {new_model}")
            else:
                self.print_error(f"切换失败，可用: {self.agent.llm.get_available_providers()}")
        elif cmd == "/history":
            if not self.history:
                self.print_info("暂无历史记录")
            else:
                self.paginate_input()
        elif cmd.startswith("/memory "):
            query = cmd[8:].strip()
            results = self.agent.remember(query, top_k=5)
            if not results:
                self.print_info(f"没有找到关于「{query}」的记忆")
            else:
                self._println(f"\n🔍 关于「{query}」的记忆：", "bold")
                for r in results:
                    self._println(f"  • {r['content'][:100]}", "dim")
        elif cmd == "/cron":
            if hasattr(self.agent, "cron"):
                jobs = self.agent.cron.list_jobs()
                self.print_cron_table([j.to_dict() for j in jobs])
            else:
                self.print_error("Cron 未初始化")
        elif cmd == "/addcron":
            self._println("添加定时任务（交互式）...")
            self._println("格式: /addcron <name> <schedule> <prompt>")
            self._println("示例: /addcron 早安report every day 9:00 给我一份今日简报")
        elif cmd.startswith("/addcron "):
            parts = cmd[9:].split(" ", 2)
            if len(parts) >= 3:
                name, schedule, prompt = parts
                if hasattr(self.agent, "cron"):
                    job = self.agent.cron.create_job(prompt, schedule, name)
                    self.print_success(f"已创建定时任务: {job.job_id}")
                else:
                    self.print_error("Cron 未初始化")
            else:
                self.print_error("参数不足: /addcron <name> <schedule> <prompt>")
        else:
            self._println(f"未知命令: {cmd}，输入 /help 查看帮助", "yellow")
        return False

    # ======== 主循环 ========

    def run(self):
        """启动 TUI 主循环"""
        self.running = True
        os.system("clear" if os.name != "nt" else "cls")
        self.print_banner()
        self.print_welcome()
        self._println(f"\n💡 输入消息开始对话，/help 查看命令\n", "dim")

        while self.running:
            try:
                # 读取输入
                prompt = input("\n你: ").strip()

                if not prompt:
                    continue

                # 命令模式
                if prompt.startswith("/"):
                    should_exit = self.handle_command(prompt)
                    if should_exit:
                        break
                    continue

                # 对话模式
                self.history.append({
                    "role": "user",
                    "content": prompt,
                    "timestamp": datetime.now().strftime("%H:%M")
                })

                # 显示加载
                stop_spinner = self.show_spinner("思考中")

                # 调用 agent
                try:
                    response = self.agent.chat(prompt)
                    stop_spinner()

                    # 显示响应
                    self.history.append({
                        "role": "assistant",
                        "content": response,
                        "timestamp": datetime.now().strftime("%H:%M")
                    })
                    self.print_message("assistant", response)

                except Exception as e:
                    stop_spinner()
                    self.print_error(str(e))

            except KeyboardInterrupt:
                self._println("\n\n👋 再见！", "bold")
                break
            except EOFError:
                break

        self.running = False


class TUIBootstrap:
    """TUI 启动器"""

    @staticmethod
    def launch(agent: "Artemis"):
        """启动 TUI"""
        tui = ArtemisTUI(agent)
        tui.run()