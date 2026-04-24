"""
Artemis 工具注册表

核心设计（参考 Hermes tools/registry.py）：
- 每个工具模块在文件级别调用 registry.register() 注册
- registry.py 用 AST 扫描发现所有工具模块
- 支持工具集（toolset）分组和可用性检查
- 线程安全的单例注册表
"""

import ast
import importlib
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  工具条目
# ═══════════════════════════════════════════════════════════════════

class ToolEntry:
    """
    单个工具的元数据容器。
    
    Attributes:
        name: 工具唯一名称
        toolset: 所属工具集（file/terminal/web/browser/memory 等）
        schema: JSON Schema 格式的工具参数定义
        handler: 同步处理函数 async_func(context, **kwargs) -> dict
        is_async: 是否异步工具
        description: 工具简短描述
        danger_level: 危险等级 0-3（0=安全，3=高危）
        requires_approval: 是否需要明确审批
    """

    __slots__ = (
        "name", "toolset", "schema", "handler",
        "is_async", "description", "danger_level",
        "requires_approval",
    )

    def __init__(
        self,
        name: str,
        toolset: str,
        schema: Dict[str, Any],
        handler: Callable,
        is_async: bool = False,
        description: str = "",
        danger_level: int = 0,
        requires_approval: bool = False,
    ):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.is_async = is_async
        self.description = description
        self.danger_level = danger_level      # 0=安全, 1=注意, 2=警告, 3=危险
        self.requires_approval = requires_approval  # 高危工具需审批

    def to_llm_format(self) -> Dict[str, Any]:
        """转换为 LLM 函数调用格式"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.schema,
        }


# ═══════════════════════════════════════════════════════════════════
#  注册表
# ═══════════════════════════════════════════════════════════════════

class ToolRegistry:
    """
    线程安全的工具注册表单例。
    
    支持：
    - AST 自动发现 tools/*.py 中的工具
    - 按名称/工具集查询
    - 动态注册/注销
    """

    _instance: Optional["ToolRegistry"] = None
    _lock_init = threading.Lock()

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            with cls._lock_init:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tools: Dict[str, ToolEntry] = {}
        self._lock = threading.RLock()
        self._discovered_toolsets: Dict[str, bool] = {}  # toolset -> available
        self._initialized = True

    # ── 注册 / 注销 ────────────────────────────────────────────────

    def register(self, entry: ToolEntry) -> None:
        """注册一个工具条目"""
        with self._lock:
            if entry.name in self._tools:
                logger.warning("工具 %s 已存在，将被覆盖", entry.name)
            self._tools[entry.name] = entry
            logger.debug("注册工具: %s (toolset=%s, danger=%d)",
                         entry.name, entry.toolset, entry.danger_level)

    def unregister(self, name: str) -> bool:
        """注销工具，返回是否成功"""
        with self._lock:
            return bool(self._tools.pop(name, None))

    def register_toolset_check(self, toolset: str, check_fn: Callable[[], bool]) -> None:
        """注册工具集可用性检查函数"""
        with self._lock:
            self._discovered_toolsets[toolset] = check_fn

    # ── 查询 ──────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ToolEntry]:
        """按名称获取工具"""
        with self._lock:
            return self._tools.get(name)

    def list_all(self) -> List[ToolEntry]:
        """列出所有已注册工具"""
        with self._lock:
            return list(self._tools.values())

    def list_by_toolset(self, toolset: str) -> List[ToolEntry]:
        """列出指定工具集中的所有工具"""
        with self._lock:
            return [t for t in self._tools.values() if t.toolset == toolset]

    def get_toolsets(self) -> List[str]:
        """列出所有已注册的工具集名称"""
        with self._lock:
            return sorted({t.toolset for t in self._tools.values()})

    def get_dangerous_tools(self) -> List[ToolEntry]:
        """获取所有需要审批的高危工具（danger_level >= 2）"""
        with self._lock:
            return [t for t in self._tools.values() if t.requires_approval]

    def get_llm_tool_schemas(self) -> List[Dict[str, Any]]:
        """获取所有工具的 LLM Schema（用于 function call）"""
        with self._lock:
            return [t.to_llm_format() for t in self._tools.values()]


# ═══════════════════════════════════════════════════════════════════
#  模块级便利函数
# ═══════════════════════════════════════════════════════════════════

_registry = ToolRegistry()


def register_tool(
    name: str,
    toolset: str,
    schema: Dict[str, Any],
    handler: Callable,
    is_async: bool = False,
    description: str = "",
    danger_level: int = 0,
    requires_approval: bool = False,
) -> None:
    """注册工具的便利函数（工具模块调用）"""
    entry = ToolEntry(
        name=name,
        toolset=toolset,
        schema=schema,
        handler=handler,
        is_async=is_async,
        description=description,
        danger_level=danger_level,
        requires_approval=requires_approval,
    )
    _registry.register(entry)


def get_registry() -> ToolRegistry:
    """获取全局注册表单例"""
    return _registry


# ═══════════════════════════════════════════════════════════════════
#  AST 工具发现
# ═══════════════════════════════════════════════════════════════════

def _is_register_call(node: ast.AST) -> bool:
    """判断 node 是否为 registry.register(...) 调用（模块级别）"""
    if not isinstance(node, ast.Expr):
        return False
    call = node.value
    if not isinstance(call, ast.Call):
        return False
    func = call.function if hasattr(call, "function") else getattr(call, "func", None)
    if func is None:
        return False
    # 匹配 registry.register(...) 或 register_tool(...)
    if isinstance(func, ast.Name):
        return func.id in ("register_tool",)
    if isinstance(func, ast.Attribute):
        return func.attr == "register" and isinstance(func.value, ast.Name) and func.value.id == "registry"
    return False


def _module_has_register_call(module_path: Path) -> bool:
    """检查模块是否包含顶层 register 调用"""
    try:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
    except (OSError, SyntaxError):
        return False
    return any(_is_register_call(stmt) for stmt in tree.body)


def discover_tools(tools_dir: Optional[Path] = None) -> List[str]:
    """
    自动发现并导入 tools/ 目录下的所有工具模块。
    
    扫描所有 *.py 文件（排除 __init__.py 和 registry.py），
    过滤包含 register_tool(...) 调用的模块并执行导入。
    
    Returns:
        已成功导入的模块名列表
    """
    tools_path = Path(tools_dir) if tools_dir else Path(__file__).resolve().parent
    
    module_names = [
        f"tools.{path.stem}"
        for path in sorted(tools_path.glob("*.py"))
        if path.name not in {"__init__.py", "registry.py", "__pycache__"}
        and _module_has_register_call(path)
    ]
    
    imported = []
    for mod_name in module_names:
        try:
            importlib.import_module(mod_name)
            imported.append(mod_name)
            logger.info("导入工具模块: %s", mod_name)
        except Exception as e:
            logger.warning("无法导入工具模块 %s: %s", mod_name, e)
    
    return imported
