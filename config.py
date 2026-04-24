"""
Artemis 配置管理系统

参考 Hermes hermes_cli/config.py 的 schema versioning 设计：
- CURRENT_SCHEMA_VERSION: 当前版本号
- DEFAULT_CONFIG: 完整默认配置
- migrate_config(): 增量迁移函数
- load_config(): 加载 + 自动迁移
"""

import copy
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Schema 版本
# ═══════════════════════════════════════════════════════════════

CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_VERSION = 1


# ═══════════════════════════════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════════════════════════════

DEFAULT_CONFIG: Dict[str, Any] = {
    # Schema 版本（用于迁移）
    "_schema_version": CURRENT_SCHEMA_VERSION,

    # 模型配置
    "model": {
        "text": "minimax:abab6.5s-chat",
        "vision": "openrouter:openai/gpt-4o-mini",
        "reasoning": "openrouter:openai/gpt-4o-mini",
    },

    # 路由配置
    "routing": {
        "text_default": "minimax",
        "vision_primary": "openrouter",
        "vision_fallback": "local",
    },

    # 工具配置
    "tools": {
        "enabled_toolsets": ["file", "memory", "web"],
        "disabled_tools": [],
        "max_file_size_mb": 10,
        "terminal_timeout": 60,
    },

    # 记忆配置
    "memory": {
        "db_path": "~/.hermes/artemis/memories/memory.db",
        "max_memories": 10000,
        "similarity_threshold": 0.01,
    },

    # Telegram Bot 配置
    "telegram": {
        "enabled": False,
        "allowed_users": [],  # 空=允许所有人
        "reply_to_message": True,
        "streaming": False,
    },

    # Agent 配置
    "agent": {
        "max_turns": 20,
        "max_tokens_per_message": 500,
        "context_window": 128000,
        "auto_save": True,
    },

    # 安全配置
    "security": {
        "approve_all": False,      # True=所有工具需确认
        "block_high_danger": True, # 高危工具强制阻断
        "dangerous_commands_log": "~/.hermes/artemis/logs/commands.log",
    },

    # 显示配置
    "display": {
        "show_cost": True,
        "show_provider": True,
        "show_thinking": False,
    },
}


# ═══════════════════════════════════════════════════════════════
#  配置迁移
# ═══════════════════════════════════════════════════════════════

def _migrate_v1_to_v2(config: Dict[str, Any]) -> Dict[str, Any]:
    """v1 → v2: 添加安全配置"""
    if "security" not in config:
        config["security"] = copy.deepcopy(DEFAULT_CONFIG["security"])
        logger.info("迁移: security 配置已添加")
    if "display" not in config:
        config["display"] = copy.deepcopy(DEFAULT_CONFIG["display"])
        logger.info("迁移: display 配置已添加")
    return config


_MIGRATIONS = {
    2: _migrate_v1_to_v2,
}


def migrate_config(config: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    执行配置迁移（按顺序应用所有需要的迁移）。
    
    Returns:
        (迁移后的配置, 是否有迁移发生)
    """
    current_version = config.get("_schema_version", 0)
    migrated = False

    while current_version < CURRENT_SCHEMA_VERSION:
        migration_fn = _MIGRATIONS.get(current_version + 1)
        if migration_fn is None:
            logger.warning("未找到迁移函数 v%d → v%d，跳过", current_version, current_version + 1)
            current_version += 1
            continue

        logger.info("执行迁移: v%d → v%d", current_version, current_version + 1)
        config = migration_fn(config)
        current_version += 1
        migrated = True
        config["_schema_version"] = current_version

    return config, migrated


# ═══════════════════════════════════════════════════════════════
#  配置加载 / 保存
# ═══════════════════════════════════════════════════════════════

def _get_config_path() -> Path:
    """获取配置文件路径"""
    return Path("~/.hermes/artemis/config.yaml").expanduser().resolve()


def load_config() -> Dict[str, Any]:
    """
    加载配置（带自动迁移）。
    
    流程：
    1. 如果配置文件不存在 → 创建默认配置
    2. 如果 _schema_version < CURRENT_SCHEMA_VERSION → 执行迁移
    3. 合并默认配置（保留用户设置，填充缺失字段）
    """
    config_path = _get_config_path()

    # 情况1: 配置文件不存在 → 创建
    if not config_path.exists():
        logger.info("配置文件不存在，创建默认配置: %s", config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config)
        return config

    # 加载现有配置
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("加载配置文件失败: %s，使用默认配置", e)
        return copy.deepcopy(DEFAULT_CONFIG)

    # 验证 schema 版本
    schema_version = config.get("_schema_version", 0)
    if schema_version < MIN_SUPPORTED_VERSION:
        logger.warning("Schema 版本 %d < %d，不支持，使用默认配置",
                       schema_version, MIN_SUPPORTED_VERSION)
        return copy.deepcopy(DEFAULT_CONFIG)

    # 执行迁移
    if schema_version < CURRENT_SCHEMA_VERSION:
        logger.info("检测到配置需迁移: v%d → v%d", schema_version, CURRENT_SCHEMA_VERSION)
        config, migrated = migrate_config(config)
        if migrated:
            save_config(config)
            logger.info("配置迁移完成并已保存")

    # 合并默认配置（填充缺失字段，不覆盖用户设置）
    config = _merge_with_defaults(config)

    return config


def _merge_with_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """将默认配置与用户配置深度合并"""
    result = copy.deepcopy(DEFAULT_CONFIG)

    def _deep_merge(base: Dict, override: Dict) -> Dict:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = _deep_merge(base[key], value)
            else:
                base[key] = copy.deepcopy(value)
        return base

    return _deep_merge(result, config)


def save_config(config: Dict[str, Any]) -> None:
    """保存配置到文件"""
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # 确保 schema 版本已写入
    config["_schema_version"] = CURRENT_SCHEMA_VERSION

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # 设置文件权限（仅本人读写）
    os.chmod(config_path, 0o600)
    logger.debug("配置已保存: %s", config_path)


def get_config_value(key_path: str, default: Any = None) -> Any:
    """
    按点分路径获取配置值。
    
    Examples:
        get_config_value("model.text")
        get_config_value("telegram.enabled")
    """
    config = load_config()
    keys = key_path.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
        if value is None:
            return default
    return value


def set_config_value(key_path: str, value: Any) -> None:
    """按点分路径设置配置值（支持嵌套）"""
    config = load_config()
    keys = key_path.split(".")
    target = config
    for k in keys[:-1]:
        if k not in target:
            target[k] = {}
        target = target[k]
    target[keys[-1]] = value
    save_config(config)
