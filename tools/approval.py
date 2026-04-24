"""
危险命令审批系统

当工具的 requires_approval=True 时，在此检查是否需要用户确认。
支持两种模式：
- APPROVE_ALL=False（默认）：静默记录，只有高危(danger_level=3)才阻断
- APPROVE_ALL=True：全部需要确认
"""

import re
from typing import Any, Dict, Optional, Tuple

from .registry import ToolEntry


# ═══════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════

# APPROVE_ALL=True 时，所有工具调用都需要确认
APPROVE_ALL = False

# 高危工具（danger_level >= 3）必须阻断
BLOCK_HIGH_DANGER = True

# 审批历史记录文件
APPROVAL_LOG = "~/.hermes/artemis/logs/approvals.log"


# ═══════════════════════════════════════════════════════════════
#  审批结果
# ═══════════════════════════════════════════════════════════════

class ApprovalResult:
    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_CONFIRMATION = "needs_confirmation"  # 需用户确认
    BLOCKED = "blocked"  # 高危被强制阻断


# ═══════════════════════════════════════════════════════════════
#  审批检查
# ═══════════════════════════════════════════════════════════════

def check_dangerous_pattern(tool_name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
    """
    检查参数中是否存在危险模式。
    
    Returns:
        (is_dangerous, reason)
    """
    args_str = str(args).lower()

    # 路径穿越检测
    if ".." in args_str and ("path" in args_str or "file" in args_str or "dir" in args_str):
        return True, "检测到路径穿越模式 (..)"

    # 敏感路径写入
    sensitive_write = [
        "/etc/", "/usr/bin/", "/usr/sbin/",
        "/root/.ssh/", "/home/", "/var/www/",
        ".ssh/id_rsa", ".ssh/id_ed25519",
        "/.dockerenv", "/var/run/docker.sock",
    ]
    if tool_name in ("write_file", "terminal") and any(s in args_str for s in sensitive_write):
        # 允许用户目录
        if "~" in args_str or "/root/" in args_str or "/home/" in args_str:
            return False, ""
        return True, f"检测到系统敏感路径写入: {args_str[:100]}"

    # 远程代码执行
    if tool_name == "terminal":
        rce_patterns = [
            r"curl\s+\|", r"wget\s+.*\|", r"eval\s*\(", r"exec\s*\(",
            r"bash\s+-i", r"nc\s+-e", r"/dev/tcp/",
            r"python.*-c\s+import", r"perl.*-e\s+",
        ]
        for pat in rce_patterns:
            if re.search(pat, args_str):
                return True, f"检测到远程代码执行模式: {pat}"

    return False, ""


def should_require_approval(entry: ToolEntry, args: Dict[str, Any]) -> Tuple[bool, str]:
    """
    判断是否需要审批。
    
    Returns:
        (needs_approval, reason)
    """
    # APPROVE_ALL 模式
    if APPROVE_ALL:
        return True, "APPROVE_ALL 模式已启用"

    # 高危工具
    if entry.requires_approval:
        return True, f"工具 {entry.name} 被标记为需要审批"

    # 危险级别 >= 3
    if entry.danger_level >= 3:
        dangerous, reason = check_dangerous_pattern(entry.name, args)
        if dangerous:
            return True, f"高危工具危险参数检测: {reason}"
        return True, f"高危工具 (level={entry.danger_level})"

    # 危险级别 >= 2
    if entry.danger_level >= 2:
        dangerous, reason = check_dangerous_pattern(entry.name, args)
        if dangerous:
            return True, f"危险参数检测: {reason}"

    return False, ""


def check_and_approve(entry: ToolEntry, args: Dict[str, Any], user_confirmed: bool = False) -> ApprovalResult:
    """
    完整审批流程。
    
    Args:
        entry: 工具条目
        args: 调用参数
        user_confirmed: 用户是否已确认（用于交互式审批流）
    
    Returns:
        ApprovalResult 之一
    """
    needs_approval, reason = should_require_approval(entry, args)

    if not needs_approval:
        _log_approval(entry.name, args, ApprovalResult.APPROVED, reason="自动批准")
        return ApprovalResult.APPROVED

    # 高危工具强制阻断（除非特别配置）
    if entry.danger_level >= 3 and BLOCK_HIGH_DANGER:
        dangerous, _ = check_dangerous_pattern(entry.name, args)
        if dangerous:
            _log_approval(entry.name, args, ApprovalResult.BLOCKED, reason=reason)
            return ApprovalResult.BLOCKED

    # 需要用户确认
    if user_confirmed:
        _log_approval(entry.name, args, ApprovalResult.APPROVED, reason=f"用户确认: {reason}")
        return ApprovalResult.APPROVED
    else:
        return ApprovalResult.NEEDS_CONFIRMATION


def _log_approval(tool_name: str, args: Dict, result: str, reason: str = "") -> None:
    """记录审批日志"""
    try:
        import os
        from datetime import datetime
        log_path = os.path.expanduser(APPROVAL_LOG)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        entry = json.dumps({
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "args": {k: str(v)[:100] for k, v in args.items()},
            "result": result,
            "reason": reason,
        }, ensure_ascii=False)
        with open(log_path, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  用户交互审批（供 agent.py 调用）
# ═══════════════════════════════════════════════════════════════

def format_approval_request(entry: ToolEntry, args: Dict[str, Any]) -> str:
    """生成用户确认提示文本"""
    lines = [
        f"⚠️  工具调用需要确认",
        f"工具: {entry.name}",
        f"描述: {entry.description}",
        f"危险级别: {entry.danger_level}/3",
        f"参数:",
    ]
    for k, v in args.items():
        if k != "context":
            lines.append(f"  {k}: {str(v)[:80]}")
    lines.append("")
    lines.append("是否批准？（输入 yes 确认，其他拒绝）")
    return "\n".join(lines)


def confirm_tool_use(entry: ToolEntry, args: Dict[str, Any], user_input: str) -> bool:
    """处理用户确认输入"""
    result = check_and_approve(entry, args, user_confirmed=False)
    if result == ApprovalResult.NEEDS_CONFIRMATION:
        # 由 agent.py 展示确认请求，这里直接解析用户响应
        approved = user_input.strip().lower() in ("yes", "y", "是", "确认", "ok", "approve")
        if approved:
            check_and_approve(entry, args, user_confirmed=True)
            return True
        else:
            _log_approval(entry.name, args, ApprovalResult.DENIED, reason="用户拒绝")
            return False
    # 已自动批准或已阻断
    return result == ApprovalResult.APPROVED


# ═══════════════════════════════════════════════════════════════
#  便捷函数（供 agent.py 使用）
# ═══════════════════════════════════════════════════════════════

def pre_execute_check(tool_name: str, args: Dict[str, Any], registry) -> Tuple[bool, str]:
    """
    工具执行前的最终检查。
    
    Returns:
        (can_execute, message)
    """
    entry = registry.get(tool_name)
    if not entry:
        return True, ""  # 未知工具不拦截

    result = check_and_approve(entry, args)
    if result == ApprovalResult.APPROVED:
        return True, ""
    elif result == ApprovalResult.BLOCKED:
        return False, f"工具 {tool_name} 被安全系统阻断（高危参数）"
    elif result == ApprovalResult.NEEDS_CONFIRMATION:
        return False, format_approval_request(entry, args)
    else:
        return False, f"工具 {tool_name} 被拒绝"


import json  # for _log_approval
