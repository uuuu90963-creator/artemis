"""
记忆工具 - 搜索、添加、删除长期记忆
"""

import json
from typing import Any, Dict, List

from .registry import register_tool

# 注意：实际 MemoryStore 实例由 agent.py 注入
# 这里只定义 schema 和处理函数签名


def _memory_search_handler(context: Dict, query: str = "", top_k: int = 5, **kwargs) -> Dict[str, Any]:
    """语义搜索记忆"""
    mem_store = context.get("memory_store")
    if not mem_store:
        return {"success": False, "error": "记忆存储未初始化"}
    try:
        results = mem_store.search_memories(query, top_k=top_k)
        return {"success": True, "results": results, "count": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _memory_add_handler(context: Dict, content: str = "", tags: List[str] = None, source: str = "", **kwargs) -> Dict[str, Any]:
    """添加记忆"""
    mem_store = context.get("memory_store")
    if not mem_store:
        return {"success": False, "error": "记忆存储未初始化"}
    try:
        mem_id = mem_store.add_memory(content, tags=tags or [], source=source)
        return {"success": True, "id": mem_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _memory_recall_handler(context: Dict, query: str = "", **kwargs) -> Dict[str, Any]:
    """检索相关记忆（简洁摘要）"""
    mem_store = context.get("memory_store")
    if not mem_store:
        return {"success": False, "error": "记忆存储未初始化"}
    try:
        results = mem_store.search_memories(query, top_k=3)
        if not results:
            return {"success": True, "content": "没有找到相关记忆", "count": 0}
        summaries = [f"[{r.get('similarity', 0):.2f}] {r.get('content', '')[:100]}" for r in results]
        return {
            "success": True,
            "content": "相关记忆:\n" + "\n".join(summaries),
            "count": len(results),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool(
    name="memory_search",
    toolset="memory",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询"},
            "top_k": {"type": "integer", "description": "返回数量", "default": 5},
        },
        "required": ["query"],
    },
    handler=_memory_search_handler,
    description="语义搜索长期记忆（TF-IDF 向量相似度）",
    danger_level=0,  # 安全
)

register_tool(
    name="memory_add",
    toolset="memory",
    schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "记忆内容"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
            "source": {"type": "string", "description": "来源"},
        },
        "required": ["content"],
    },
    handler=_memory_add_handler,
    description="添加新的长期记忆（带标签）",
    danger_level=0,
)

register_tool(
    name="memory_recall",
    toolset="memory",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "回忆相关上下文"},
        },
        "required": ["query"],
    },
    handler=_memory_recall_handler,
    description="快速检索相关记忆用于上下文（精简摘要）",
    danger_level=0,
)
