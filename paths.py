#!/usr/bin/env python3
"""
Artemis 路径系统 - 兼容 OpenClaw 工作区和 Hermes 双生态

支持：
- ARTEMIS_HOME 环境变量（最高优先级）
- 当前仓库目录直接运行
- ~/.hermes/artemis 作为 fallback
- OpenClaw 工作区 skill 目录自动发现
- ARTEMIS_ENV_FILE 自定义环境变量文件
"""

import os
import sys
from pathlib import Path
from typing import Optional, List


def _get_repo_root() -> Optional[Path]:
    """获取当前仓库根目录（用于直接运行）"""
    # 向上查找包含关键文件的目录
    current = Path(__file__).parent.resolve()
    markers = ["artemis.py", "config.yaml", ".git", "README.md"]
    for parent in [current] + list(current.parents):
        if any((parent / m).exists() for m in markers):
            return parent
    return None


# ═══════════════════════════════════════════════════════════
#  路径解析
# ═══════════════════════════════════════════════════════════

# 优先级：ARTEMIS_HOME > 当前仓库 > ~/.hermes/artemis
_ARTEMIS_HOME: Optional[Path] = None
_OPENCLAW_WORKSPACE: Optional[Path] = None


def get_artemis_home() -> Path:
    """获取 Artemis 主目录"""
    global _ARTEMIS_HOME
    if _ARTEMIS_HOME is not None:
        return _ARTEMIS_HOME

    if os.environ.get("ARTEMIS_HOME"):
        _ARTEMIS_HOME = Path(os.environ["ARTEMIS_HOME"]).resolve()
    elif (repo_root := _get_repo_root()) and (repo_root / "artemis.py").exists():
        _ARTEMIS_HOME = repo_root
    else:
        _ARTEMIS_HOME = Path.home() / ".hermes" / "artemis"

    return _ARTEMIS_HOME


def get_openclaw_workspace() -> Optional[Path]:
    """获取 OpenClaw 工作区目录（如果存在）"""
    global _OPENCLAW_WORKSPACE
    if _OPENCLAW_WORKSPACE is not None:
        return _OPENCLAW_WORKSPACE

    workspace = Path.home() / ".hermes"
    if workspace.exists() and (workspace / "skills").exists():
        _OPENCLAW_WORKSPACE = workspace
        return _OPENCLAW_WORKSPACE

    # 尝试从环境变量
    if os.environ.get("OPENCLAW_WORKSPACE"):
        _OPENCLAW_WORKSPACE = Path(os.environ["OPENCLAW_WORKSPACE"])
        return _OPENCLAW_WORKSPACE

    return None


def get_env_file() -> Path:
    """获取环境变量文件路径"""
    if env_file := os.environ.get("ARTEMIS_ENV_FILE"):
        return Path(env_file).resolve()
    return Path.home() / ".hermes" / ".env"


def get_config_path() -> Path:
    """获取配置文件路径"""
    return get_artemis_home() / "config.yaml"


def get_skills_dirs() -> List[Path]:
    """获取所有 skill 目录（Artemis 本地 + OpenClaw 工作区）"""
    dirs = []

    # Artemis 本地 skills
    artemis_skills = get_artemis_home() / "skills"
    if artemis_skills.exists():
        dirs.append(artemis_skills)

    # OpenClaw 工作区 skills
    openclaw = get_openclaw_workspace()
    if openclaw and (openclaw / "skills").exists():
        dirs.append(openclaw / "skills")

    return dirs


def get_memories_dir() -> Path:
    """获取记忆数据库目录"""
    mem_dir = get_artemis_home() / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def get_logs_dir() -> Path:
    """获取日志目录"""
    log_dir = get_artemis_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_workspace_dir() -> Path:
    """获取工作区目录"""
    ws = get_artemis_home() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ═══════════════════════════════════════════════════════════
#  Python Path 管理
# ═══════════════════════════════════════════════════════════

def setup_python_path():
    """将 Artemis 目录加入 sys.path（如果尚未加入）"""
    home = str(get_artemis_home())
    if home not in sys.path:
        sys.path.insert(0, home)


# ═══════════════════════════════════════════════════════════
#  初始化
# ═══════════════════════════════════════════════════════════

def resolve_path(path: str) -> Path:
    """解析相对路径（基于 ARTEMIS_HOME）"""
    p = Path(path)
    if p.is_absolute():
        return p
    return get_artemis_home() / path


# 设置默认 home（立即解析，避免后续循环依赖）
get_artemis_home()
