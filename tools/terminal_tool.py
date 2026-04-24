"""
终端工具 - 执行 Shell 命令
"""

import subprocess
from typing import Any, Dict

from .registry import register_tool

# ═══════════════════════════════════════════════════════════════
#  危险命令黑名单
# ═══════════════════════════════════════════════════════════════

_DANGEROUS_COMMANDS = frozenset({
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
    ":(){:|:&};:",  # fork bomb
    "curl | sh", "wget | sh",
    "chmod -R 777 /", "chmod 000 /",
    "> /dev/sda", "dd of=/dev/sda",
    "mv / /dev/null", "cp /dev/null /etc/passwd",
})


def _is_command_safe(cmd: str) -> tuple[bool, str]:
    """检查命令是否安全"""
    cmd_lower = cmd.lower().strip()
    for dangerous in _DANGEROUS_COMMANDS:
        if dangerous in cmd_lower:
            return False, f"危险命令: {dangerous}"
    # 警告：sudo without password
    if "sudo" in cmd_lower and "noppw" not in cmd_lower and not cmd_lower.startswith("sudo -n"):
        return True, "WARN: sudo 命令（未验证是否需要密码）"
    return True, ""


def _terminal_handler(context: Dict, command: str = "", timeout: int = 60, workdir: str = None, **kwargs) -> Dict[str, Any]:
    """
    执行 Shell 命令
    
    Args:
        command: shell 命令
        timeout: 超时秒数（默认60）
        workdir: 工作目录
    """
    safe, reason = _is_command_safe(command)
    if not safe:
        return {"success": False, "error": reason, "danger": True}

    warnings = []
    if "WARN:" in reason:
        warnings.append(reason)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=min(timeout, 300),  # 最长 5 分钟
            cwd=workdir,
        )
        output = result.stdout.strip() if result.stdout else ""
        error = result.stderr.strip() if result.stderr else ""

        if warnings and result.returncode != 0:
            warnings.append(f"命令失败 (exit {result.returncode})")

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": output[:5000],  # 限制输出长度
            "stderr": error[:2000],
            "warnings": warnings,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"命令超时（>{timeout}s）", "danger": False}
    except Exception as e:
        return {"success": False, "error": str(e), "danger": False}


register_tool(
    name="terminal",
    toolset="terminal",
    schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell 命令"},
            "timeout": {"type": "integer", "description": "超时秒数", "default": 60},
            "workdir": {"type": "string", "description": "工作目录"},
        },
        "required": ["command"],
    },
    handler=_terminal_handler,
    description="执行 Shell 命令（黑名单保护，禁止危险操作）",
    danger_level=3,  # 高危
    requires_approval=True,
)
