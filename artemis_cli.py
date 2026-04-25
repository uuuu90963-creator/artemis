#!/usr/bin/env python3
"""
Artemis CLI 入口

用法:
    artemis                    # 交互式聊天
    artemis run <任务>         # 单次任务
    artemis tools [toolset]    # 列出工具
    artemis status             # 显示状态
    artemis setup              # 交互式配置
    artemis approval list      # 审批日志
"""

import argparse
import sys
import os
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from tools.registry import discover_tools, get_registry
from tools.approval import APPROVAL_LOG, _log_approval, ApprovalResult
from artemis import Artemis


# ═══════════════════════════════════════════════════════════════
#  Banner
# ═══════════════════════════════════════════════════════════════

BANNER = r"""
    ██╗    ██╗ █████╗ ██████╗ ██████╗
    ██║    ██║██╔══██╗██╔══██╗██╔══██╗
    ██║ █╗ ██║███████║██████╔╝██████╔╝
    ██║███╗██║██╔══██║██╔══██╗██╔══██╗
    ╚███╔███╔╝██║  ██║██║  ██║██║  ██║
     ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    通用 AI 助手  |  v1.0
    输入 exit 退出，输入 tools 查看工具列表
"""


# ═══════════════════════════════════════════════════════════════
#  初始化
# ═══════════════════════════════════════════════════════════════

def _ensure_init():
    """延迟初始化（避免循环 import）"""
    if not hasattr(_ensure_init, "_done"):
        discover_tools()
        _ensure_init._done = True


# ═══════════════════════════════════════════════════════════════
#  命令实现
# ═══════════════════════════════════════════════════════════════

def cmd_status(args):
    """显示状态"""
    _ensure_init()
    reg = get_registry()
    tools = reg.list_all()
    toolsets = reg.get_toolsets()

    print(BANNER)
    print(f"注册工具: {len(tools)} 个")
    print(f"工具集: {', '.join(toolsets)}")
    print()

    dangerous = [t for t in tools if t.danger_level >= 2]
    if dangerous:
        print(f"⚠️  高危工具 ({len(dangerous)}):")
        for t in dangerous:
            print(f"  [{t.danger_level}] {t.name} - {t.description[:50]}")
        print()

    # 检查配置文件
    config_path = Path("~/.hermes/artemis/config.yaml").expanduser()
    env_path = Path("~/.hermes/.env").expanduser()
    print(f"配置: {'✓' if config_path.exists() else '✗'} {config_path}")
    print(f"环境变量: {'✓' if env_path.exists() else '✗'} {env_path}")


def cmd_tools(args):
    """列出工具"""
    _ensure_init()
    reg = get_registry()

    if args.toolset:
        tools = reg.list_by_toolset(args.toolset)
    else:
        tools = reg.list_all()

    tools_by_toolset = {}
    for t in tools:
        tools_by_toolset.setdefault(t.toolset, []).append(t)

    for ts, tlist in sorted(tools_by_toolset.items()):
        print(f"\n## {ts.upper()} ({len(tlist)})")
        for t in tlist:
            danger = "🔴" if t.danger_level >= 3 else ("🟡" if t.danger_level >= 2 else "🟢")
            approval = "⚡" if t.requires_approval else "  "
            print(f"  {danger}{approval} {t.name}: {t.description[:45]}")


def cmd_run(args):
    """执行单次任务"""
    _ensure_init()

    if not args.task:
        print("错误: 请提供任务描述", file=sys.stderr)
        sys.exit(1)

    agent = Artemis()
    print(f"> {args.task}", flush=True)
    result = agent.run_task({"content": args.task})
    print()
    content = result.get("content", "")
    print(content if content else "完成")


def cmd_approval(args):
    """审批日志"""
    log_path = Path(APPROVAL_LOG).expanduser()
    if not log_path.exists():
        print("暂无审批记录")
        return

    records = []
    with open(log_path) as f:
        for line in f:
            try:
                records.append(json.loads(line.strip()))
            except Exception:
                pass

    if not records:
        print("暂无审批记录")
        return

    # 显示最近 20 条
    for rec in records[-20:]:
        icon = {"approved": "✓", "denied": "✗", "blocked": "🔴", "needs_confirmation": "?"}.get(rec["result"], "?")
        print(f"{icon} [{rec['timestamp'][5:19]}] {rec['tool']}: {rec.get('reason', rec['result'])}")


def cmd_setup(args):
    """交互式配置引导"""
    print("Artemis 交互式配置向导")
    print("=" * 40)

    config_path = Path("~/.hermes/artemis/config.yaml").expanduser()
    env_path = Path("~/.hermes/.env").expanduser()

    print(f"\n配置文件: {config_path}")
    print(f"环境变量: {env_path}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # MiniMax key
    minimax_key = input("\nMiniMax API Key (直接回车跳过): ").strip()
    openrouter_key = input("OpenRouter API Key (直接回车跳过): ").strip()
    deepseek_key = input("DeepSeek API Key (直接回车跳过): ").strip()

    # 写入 .env
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text().splitlines()

    key_map = {
        "MINIMAX_API_KEY": minimax_key,
        "OPENROUTER_API_KEY": openrouter_key,
        "DEEPSEEK_API_KEY": deepseek_key,
    }
    for key, val in key_map.items():
        if val:
            # 替换或追加
            found = False
            for i, line in enumerate(env_lines):
                if line.startswith(f"{key}="):
                    env_lines[i] = f"{key}={val}"
                    found = True
                    break
            if not found:
                env_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(env_lines) + "\n")
    print(f"\n✓ 已保存到 {env_path}")

    # Telegram token
    tg_token = input("\nTelegram Bot Token (直接回车跳过): ").strip()
    if tg_token:
        with open(env_path, "a") as f:
            f.write(f"TELEGRAM_BOT_TOKEN={tg_token}\n")
        print("✓ Telegram Token 已保存")

    print("\n配置完成！运行 'artemis' 启动")


def cmd_chat(args):
    """交互式聊天"""
    _ensure_init()

    print(BANNER)
    print("提示: 输入 'tools' 查看可用工具，'exit' 退出\n")

    agent = Artemis()

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("再见！")
            break
        if user_input.lower() == "tools":
            print("\n可用工具:")
            cmd_tools(argparse.Namespace(toolset=None))
            continue

        print(f"\n思考中...\n", end="", flush=True)
        try:
            result = agent.run_task(user_input)
            content = result.get("content", result.get("error", ""))
            print(f"Artemis: {content}\n")
        except Exception as e:
            print(f"错误: {e}\n")


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Artemis - 通用 AI 助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  artemis              交互式聊天
  artemis run "帮我写一个排序算法"
  artemis tools        列出所有工具
  artemis tools file   列出文件工具
  artemis status       显示状态
  artemis approval     显示审批日志
  artemis setup        交互式配置向导
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # artemis (default: chat)
    subparsers.add_parser("chat", help="交互式聊天（默认）").set_defaults(func=cmd_chat)

    # artemis run <task>
    run_parser = subparsers.add_parser("run", help="执行单次任务")
    run_parser.add_argument("task", nargs="+", help="任务描述")
    run_parser.set_defaults(func=cmd_run)

    # artemis tools [toolset]
    tools_parser = subparsers.add_parser("tools", help="列出工具")
    tools_parser.add_argument("toolset", nargs="?", help="按工具集过滤")
    tools_parser.set_defaults(func=cmd_tools)

    # artemis status
    subparsers.add_parser("status", help="显示状态").set_defaults(func=cmd_status)

    # artemis approval
    subparsers.add_parser("approval", help="审批日志").set_defaults(func=cmd_approval)

    # artemis setup
    subparsers.add_parser("setup", help="交互式配置向导").set_defaults(func=cmd_setup)

    args = parser.parse_args()

    # 默认执行 chat
    if args.command is None:
        cmd_chat(args)
        return

    # 处理 run 命令（task 是列表）
    if args.command == "run":
        args.task = " ".join(args.task)

    args.func(args)


if __name__ == "__main__":
    main()
