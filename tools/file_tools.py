"""
文件系统工具 - 读取、写入、搜索文件
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Any, Dict

from .registry import register_tool

# ═══════════════════════════════════════════════════════════════
#  危险模式检测
# ═══════════════════════════════════════════════════════════════

# 危险路径模式（绝对路径或向上穿越）
_DANGEROUS_PATTERNS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/root/.ssh",
    "/root/.hermes/keys",
    ".ssh/id_rsa",
    ".ssh/id_ed25519",
    "authorized_keys",
    "/proc/1/environ",
    "/.dockerenv",
    "/var/run/docker.sock",
]


def _is_path_safe(path: str) -> tuple[bool, str]:
    """检查路径是否安全，返回 (安全, 原因)"""
    expanded = os.path.expanduser(os.path.expandvars(path))
    abs_path = os.path.abspath(expanded)

    for pattern in _DANGEROUS_PATTERNS:
        if pattern in abs_path:
            return False, f"危险路径: {pattern}"
    return True, ""


# ═══════════════════════════════════════════════════════════════
#  工具处理器
# ═══════════════════════════════════════════════════════════════

def _read_file_handler(context: Dict, path: str = "", offset: int = 1, limit: int = 500, **kwargs) -> Dict[str, Any]:
    """读取文件内容"""
    safe, reason = _is_path_safe(path)
    if not safe:
        return {"success": False, "error": reason}

    p = Path(path)
    if not p.exists():
        return {"success": False, "error": f"文件不存在: {path}"}
    if not p.is_file():
        return {"success": False, "error": f"不是文件: {path}"}
    if p.stat().st_size > 10 * 1024 * 1024:  # 10MB limit
        return {"success": False, "error": "文件超过 10MB 限制"}

    try:
        lines = p.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        segment = lines[offset - 1:offset - 1 + limit]
        return {
            "success": True,
            "content": "\n".join(segment),
            "total_lines": total,
            "offset": offset,
            "limit": limit,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _write_file_handler(context: Dict, path: str = "", content: str = "", **kwargs) -> Dict[str, Any]:
    """写入文件内容"""
    safe, reason = _is_path_safe(path)
    if not safe:
        return {"success": False, "error": reason}

    # 敏感文件写保护
    if path.endswith((".pem", ".key", ".env", "id_rsa", "id_ed25519")):
        return {"success": False, "error": f"禁止写入敏感文件: {path}"}

    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(p.resolve()), "bytes": len(content)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _search_files_handler(context: Dict, pattern: str = "", path: str = ".", file_glob: str = None, limit: int = 50, **kwargs) -> Dict[str, Any]:
    """搜索文件内容"""
    import re
    matches = []
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        search_path = Path(path).expanduser().resolve()
        if not search_path.exists():
            return {"success": False, "error": f"路径不存在: {path}"}

        glob_pattern = f"*{file_glob}" if file_glob else "*.py"
        for p in search_path.rglob(glob_pattern):
            if p.is_file() and not _is_path_safe(str(p))[0]:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        matches.append({"file": str(p), "line": i, "text": line[:200]})
                        if len(matches) >= limit:
                            break
            except Exception:
                pass
        return {"success": True, "matches": matches, "total": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  自动注册
# ═══════════════════════════════════════════════════════════════

register_tool(
    name="read_file",
    toolset="file",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "offset": {"type": "integer", "description": "起始行号（1开始）", "default": 1},
            "limit": {"type": "integer", "description": "最大行数", "default": 500},
        },
        "required": ["path"],
    },
    handler=_read_file_handler,
    description="读取文件内容，支持分页 offset+limit",
    danger_level=1,  # 注意：已做路径安全检查
)

register_tool(
    name="write_file",
    toolset="file",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "写入内容"},
        },
        "required": ["path", "content"],
    },
    handler=_write_file_handler,
    description="写入内容到文件（覆盖），禁止写入敏感文件",
    danger_level=2,  # 警告：写入操作
    requires_approval=True,
)

register_tool(
    name="search_files",
    toolset="file",
    schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "搜索目录", "default": "."},
            "file_glob": {"type": "string", "description": "文件过滤如 *.py"},
            "limit": {"type": "integer", "description": "最大结果数", "default": 50},
        },
        "required": ["pattern"],
    },
    handler=_search_files_handler,
    description="递归搜索文件内容（正则匹配）",
    danger_level=1,
)
