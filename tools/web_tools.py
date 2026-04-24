"""
Web 工具 - 搜索和获取网页内容
"""

import json
import urllib.request
import urllib.parse
import re
from typing import Any, Dict

from .registry import register_tool


def _web_search_handler(context: Dict, query: str = "", limit: int = 5, **kwargs) -> Dict[str, Any]:
    """Web 搜索（使用 DuckDuckGo HTML）"""
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # 解析结果
        results = re.findall(
            r'<a class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>',
            html
        )
        parsed = []
        for href, title in results[:limit]:
            parsed.append({"title": title.strip(), "url": href})

        return {"success": True, "results": parsed, "query": query, "count": len(parsed)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _web_fetch_handler(context: Dict, url: str = "", max_chars: int = 3000, **kwargs) -> Dict[str, Any]:
    """获取网页正文（去除 HTML 标签）"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # 去除脚本和样式
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        # 转文本
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()

        return {
            "success": True,
            "url": url,
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool(
    name="web_search",
    toolset="web",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "结果数量", "default": 5},
        },
        "required": ["query"],
    },
    handler=_web_search_handler,
    description="Web 搜索（DuckDuckGo HTML）",
    danger_level=1,
)

register_tool(
    name="web_fetch",
    toolset="web",
    schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "网页 URL"},
            "max_chars": {"type": "integer", "description": "最大字符数", "default": 3000},
        },
        "required": ["url"],
    },
    handler=_web_fetch_handler,
    description="获取网页正文（去除 HTML 标签）",
    danger_level=1,
)
