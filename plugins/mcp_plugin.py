"""
MCP (Model Context Protocol) 插件系统 for Artemis
轻量级实现，支持热插拔、工具声明、资源管理
"""

import json
import importlib
import importlib.util
import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
import re


def tool(name: str = None, description: str = "", parameters: Dict = None):
    """
    装饰器：标记一个函数为 MCP 工具
    
    用法：
    @tool(name="weather", description="查询天气", parameters={
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名"}},
        "required": ["city"]
    })
    def get_weather(city: str) -> str:
        return f"{city} 今天晴天，25度"
    """
    def decorator(func):
        func._is_mcp_tool = True
        func._tool_name = name or func.__name__
        func._tool_desc = description or func.__doc__ or ""
        func._tool_params = parameters or {"type": "object", "properties": {}}
        return func
    return decorator


class MCPPlugin:
    """单个 MCP 插件"""

    def __init__(self, plugin_dir: Path, manager: 'MCPPluginManager' = None):
        self.dir = Path(plugin_dir)
        self.manager = manager
        self.name: str = ""
        self.version: str = ""
        self.description: str = ""
        self.author: str = ""
        self.tags: List[str] = []
        self.tools: Dict[str, Callable] = {}
        self.resources: Dict[str, Any] = {}
        self.enabled: bool = True
        self.installed_at: str = ""
        self._tool_schemas: Dict[str, Dict] = {}
        self._module = None
        self._load()

    def _load(self):
        """加载插件"""
        plugin_json = self.dir / "plugin.json"
        if not plugin_json.exists():
            raise FileNotFoundError(f"Plugin config not found: {plugin_json}")

        # 读取 plugin.json
        with open(plugin_json, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        self.name = config.get("name", self.dir.name)
        self.version = config.get("version", "0.0.0")
        self.description = config.get("description", "")
        self.author = config.get("author", "")
        self.tags = config.get("tags", [])
        self.resources = config.get("resources", {})
        self.enabled = config.get("enabled", True)
        self.installed_at = config.get("installed_at", datetime.now().strftime("%Y-%m-%d"))

        # 加载 tools.py
        self._load_tools()

    def _load_tools(self):
        """加载工具模块"""
        tools_file = self.dir / "tools.py"
        init_file = self.dir / "__init__.py"
        
        # 优先加载 tools.py，否则尝试从 __init__.py 加载
        if tools_file.exists():
            self._module = self._import_module_from_file("tools", tools_file)
        elif init_file.exists():
            self._module = self._import_module_from_file(self.name, init_file)
        else:
            return

        if self._module is None:
            return

        # 扫描所有 @tool 装饰的函数
        for attr_name in dir(self._module):
            attr = getattr(self._module, attr_name)
            if callable(attr) and getattr(attr, '_is_mcp_tool', False):
                tool_name = getattr(attr, '_tool_name', attr_name)
                self.tools[tool_name] = attr
                self._tool_schemas[tool_name] = {
                    "name": tool_name,
                    "description": getattr(attr, '_tool_desc', ''),
                    "parameters": getattr(attr, '_tool_params', {"type": "object", "properties": {}})
                }

    def _import_module_from_file(self, module_name: str, file_path: Path):
        """从文件路径导入模块（插件隔离）"""
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return None
        
        module = importlib.util.module_from_spec(spec)
        try:
            # 保存当前 sys.modules 状态
            original_modules = set(sys.modules.keys())
            # 执行模块
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            print(f"Error loading module {module_name} from {file_path}: {e}")
            return None

    def get_tools(self) -> List[Dict]:
        """返回工具 schema 列表（用于 LLM function call）"""
        return [
            {
                "name": name,
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters", {"type": "object", "properties": {}})
            }
            for name, schema in self._tool_schemas.items()
        ]

    def call_tool(self, name: str, arguments: Dict) -> Any:
        """调用插件工具"""
        if name not in self.tools:
            raise ValueError(f"Tool '{name}' not found in plugin '{self.name}'")
        
        func = self.tools[name]
        try:
            return func(**arguments)
        except TypeError as e:
            raise ValueError(f"Invalid arguments for tool '{name}': {e}")

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "enabled": self.enabled,
            "installed_at": self.installed_at,
            "tools": list(self.tools.keys()),
            "resources": list(self.resources.keys())
        }


class MCPPluginManager:
    """MCP 插件管理器"""

    def __init__(self, plugins_dir: Path = None):
        if plugins_dir is None:
            base_dir = Path.home() / ".hermes" / "artemis"
            self.plugins_dir = base_dir / "plugins"
        else:
            # 如果传入的是 plugins 目录本身，直接用
            if plugins_dir.name == "plugins" and plugins_dir.parent.name == "artemis":
                self.plugins_dir = plugins_dir
            else:
                # 否则当作 base_dir 处理
                self.plugins_dir = plugins_dir / "plugins"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.plugins_dir / "registry.json"
        self.plugins: Dict[str, MCPPlugin] = {}
        self._ensure_registry()
        self.load_all()

    def _ensure_registry(self):
        """确保 registry.json 存在"""
        if not self.registry_path.exists():
            default_registry = {
                "version": "1.0.0",
                "plugins": []
            }
            with open(self.registry_path, 'w', encoding='utf-8') as f:
                json.dump(default_registry, f, indent=4, ensure_ascii=False)

    def _load_registry(self) -> Dict:
        """加载注册表"""
        try:
            with open(self.registry_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": "1.0.0", "plugins": []}

    def _save_registry(self, registry: Dict):
        """保存注册表"""
        with open(self.registry_path, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=4, ensure_ascii=False)

    # ======== 插件管理 ========
    def load_plugin(self, name: str) -> bool:
        """加载单个插件"""
        plugin_dir = self.plugins_dir / name
        
        # 检查插件目录
        if not plugin_dir.exists() or not plugin_dir.is_dir():
            print(f"Plugin directory not found: {plugin_dir}")
            return False
        
        # 检查 plugin.json
        plugin_json = plugin_dir / "plugin.json"
        if not plugin_json.exists():
            print(f"Plugin config not found: {plugin_json}")
            return False

        try:
            plugin = MCPPlugin(plugin_dir, self)
            self.plugins[name] = plugin
            
            # 更新注册表
            registry = self._load_registry()
            plugin_entry = {
                "name": name,
                "path": name,
                "enabled": True,
                "installed_at": plugin.installed_at
            }
            
            # 更新或添加插件条目
            for i, p in enumerate(registry["plugins"]):
                if p["name"] == name:
                    registry["plugins"][i] = plugin_entry
                    break
            else:
                registry["plugins"].append(plugin_entry)
            
            self._save_registry(registry)
            print(f"Loaded plugin: {name}")
            return True
        except Exception as e:
            print(f"Failed to load plugin '{name}': {e}")
            return False

    def unload_plugin(self, name: str) -> bool:
        """卸载插件（不移除文件，只是 unload）"""
        if name not in self.plugins:
            print(f"Plugin not loaded: {name}")
            return False

        del self.plugins[name]
        
        # 更新注册表
        registry = self._load_registry()
        for i, p in enumerate(registry["plugins"]):
            if p["name"] == name:
                registry["plugins"][i]["enabled"] = False
                break
        self._save_registry(registry)
        
        print(f"Unloaded plugin: {name}")
        return True

    def reload_plugin(self, name: str) -> bool:
        """重新加载插件"""
        if name in self.plugins:
            del self.plugins[name]
        return self.load_plugin(name)

    def install_plugin(self, source: Path) -> bool:
        """从本地目录安装插件"""
        source = Path(source)
        if not source.exists() or not source.is_dir():
            print(f"Source directory not found: {source}")
            return False

        plugin_json = source / "plugin.json"
        if not plugin_json.exists():
            print(f"Source plugin.json not found: {plugin_json}")
            return False

        try:
            # 读取插件名
            with open(plugin_json, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            plugin_name = config.get("name", source.name)
            
            # 检查是否已安装
            if (self.plugins_dir / plugin_name).exists():
                print(f"Plugin already installed: {plugin_name}")
                return False

            # 复制插件目录
            import shutil
            dest = self.plugins_dir / plugin_name
            shutil.copytree(source, dest)
            
            # 添加到注册表
            registry = self._load_registry()
            plugin_entry = {
                "name": plugin_name,
                "path": plugin_name,
                "enabled": True,
                "installed_at": datetime.now().strftime("%Y-%m-%d")
            }
            registry["plugins"].append(plugin_entry)
            self._save_registry(registry)
            
            # 加载插件
            return self.load_plugin(plugin_name)
        except Exception as e:
            print(f"Failed to install plugin: {e}")
            return False

    def uninstall_plugin(self, name: str) -> bool:
        """卸载插件（移除目录）"""
        # 先卸载
        if name in self.plugins:
            del self.plugins[name]

        plugin_dir = self.plugins_dir / name
        if not plugin_dir.exists():
            print(f"Plugin directory not found: {plugin_dir}")
            return False

        try:
            # 删除目录
            import shutil
            shutil.rmtree(plugin_dir)
            
            # 从注册表移除
            registry = self._load_registry()
            registry["plugins"] = [p for p in registry["plugins"] if p["name"] != name]
            self._save_registry(registry)
            
            print(f"Uninstalled plugin: {name}")
            return True
        except Exception as e:
            print(f"Failed to uninstall plugin '{name}': {e}")
            return False

    def list_plugins(self) -> List[Dict]:
        """列出所有插件（包含加载状态）"""
        registry = self._load_registry()
        result = []
        
        for plugin_entry in registry["plugins"]:
            name = plugin_entry["name"]
            plugin_info = {
                "name": name,
                "path": plugin_entry.get("path", name),
                "enabled": plugin_entry.get("enabled", True),
                "installed_at": plugin_entry.get("installed_at", ""),
                "loaded": name in self.plugins
            }
            
            # 如果已加载，添加更多信息
            if name in self.plugins:
                p = self.plugins[name]
                plugin_info.update({
                    "version": p.version,
                    "description": p.description,
                    "tags": p.tags,
                    "tools": list(p.tools.keys()),
                    "resources": list(p.resources.keys())
                })
            
            result.append(plugin_info)
        
        return result

    def get_plugin(self, name: str) -> Optional[MCPPlugin]:
        """获取插件实例"""
        return self.plugins.get(name)

    # ======== 工具调用 ========
    def get_all_tools(self) -> List[Dict]:
        """获取所有已加载插件的工具 schema"""
        all_tools = []
        for plugin in self.plugins.values():
            all_tools.extend(plugin.get_tools())
        return all_tools

    def call_tool(self, plugin_name: str, tool_name: str, arguments: Dict) -> Any:
        """调用指定插件的工具"""
        plugin = self.plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Plugin not found: {plugin_name}")
        
        return plugin.call_tool(tool_name, arguments)

    def call_tool_global(self, tool_name: str, arguments: Dict) -> Any:
        """全局工具调用（跨插件查找）"""
        for plugin in self.plugins.values():
            if tool_name in plugin.tools:
                return plugin.call_tool(tool_name, arguments)
        
        raise ValueError(f"Tool not found: {tool_name}")

    # ======== 辅助 ========
    def search_plugins(self, query: str) -> List[Dict]:
        """搜索插件（搜索 name/description/tags）"""
        query = query.lower()
        results = []
        
        for plugin_info in self.list_plugins():
            name = plugin_info.get("name", "").lower()
            desc = plugin_info.get("description", "").lower()
            tags = [t.lower() for t in plugin_info.get("tags", [])]
            
            if (query in name) or (query in desc) or (query in tags):
                results.append(plugin_info)
        
        return results

    def call_tools_by_schema(self, tool_calls: List[Dict]) -> List[Dict]:
        """批量调用工具（给定 LLM 返回的 function_calls 格式）"""
        results = []
        
        for call in tool_calls:
            name = call.get("name")
            arguments = call.get("arguments", {})
            
            # 解析插件名和工具名 (格式: "plugin_name.tool_name")
            if "." in name:
                parts = name.split(".", 1)
                plugin_name, tool_name = parts[0], parts[1]
            else:
                # 全局查找
                plugin_name, tool_name = None, name
                for p_name, plugin in self.plugins.items():
                    if tool_name in plugin.tools:
                        plugin_name = p_name
                        break
            
            if plugin_name is None:
                results.append({
                    "tool": name,
                    "result": None,
                    "error": f"Tool not found: {tool_name}"
                })
                continue
            
            try:
                result = self.call_tool(plugin_name, tool_name, arguments)
                results.append({
                    "tool": name,
                    "result": result,
                    "error": None
                })
            except Exception as e:
                results.append({
                    "tool": name,
                    "result": None,
                    "error": str(e)
                })
        
        return results

    def load_all(self):
        """加载所有已注册且启用的插件"""
        registry = self._load_registry()
        
        for plugin_entry in registry.get("plugins", []):
            if plugin_entry.get("enabled", True):
                name = plugin_entry.get("name")
                if name:
                    self.load_plugin(name)


# 测试代码
if __name__ == "__main__":
    print("=" * 50)
    print("MCP Plugin System Test")
    print("=" * 50)
    
    # 创建管理器（使用默认目录）
    pm = MCPPluginManager()
    
    print("\n1. 列出所有插件:")
    plugins = pm.list_plugins()
    for p in plugins:
        print(f"  - {p['name']} (loaded: {p['loaded']})")
    
    print("\n2. 获取所有工具:")
    tools = pm.get_all_tools()
    print(f"  共 {len(tools)} 个工具")
    for t in tools:
        print(f"  - {t['name']}: {t['description']}")
    
    print("\n3. 调用天气工具:")
    try:
        result = pm.call_tool("example_plugin", "weather", {"city": "包头"})
        print(f"  weather(包头) = {result}")
        
        result = pm.call_tool("example_plugin", "weather", {"city": "北京"})
        print(f"  weather(北京) = {result}")
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\n4. 调用计算器工具:")
    try:
        result = pm.call_tool("example_plugin", "calculator", {"expression": "2+3*4"})
        print(f"  calculator(2+3*4) = {result}")
        
        result = pm.call_tool("example_plugin", "calculator", {"expression": "(2+3)*4"})
        print(f"  calculator((2+3)*4) = {result}")
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\n5. 全局工具调用:")
    try:
        result = pm.call_tool_global("weather", {"city": "上海"})
        print(f"  call_tool_global(weather, 上海) = {result}")
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\n6. 搜索插件:")
    results = pm.search_plugins("example")
    print(f"  搜索 'example' 结果: {len(results)} 个")
    
    print("\n7. 批量调用工具:")
    tool_calls = [
        {"name": "weather", "arguments": {"city": "包头"}},
        {"name": "calculator", "arguments": {"expression": "100-1"}}
    ]
    results = pm.call_tools_by_schema(tool_calls)
    for r in results:
        status = "OK" if r["error"] is None else "ERROR"
        print(f"  [{status}] {r['tool']}: {r.get('result') or r.get('error')}")
    
    print("\n" + "=" * 50)
    print("Test completed!")
    print("=" * 50)
