"""示例 MCP 插件工具函数"""

import sys
from pathlib import Path

# 添加父目录到路径以便导入 mcp_plugin
_parent_dir = str(Path(__file__).parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from mcp_plugin import tool


@tool(name="weather", description="查询城市天气", parameters={
    "type": "object",
    "properties": {
        "city": {"type": "string", "description": "城市名（中文或英文）"}
    },
    "required": ["city"]
})
def get_weather(city: str) -> str:
    """返回城市天气信息"""
    # 实际可以用心知天气等 API，这里演示
    weathers = {
        "北京": "☀️ 晴天，15-25°C",
        "上海": "🌧️ 小雨，18-24°C",
        "包头": "⛅ 多云，10-22°C",
        "广州": "🌤️ 晴间多云，22-30°C",
        "深圳": "🌴 晴，23-31°C",
        "成都": "🌫️ 雾，12-20°C",
        "杭州": "🌧️ 中雨，16-24°C",
        "南京": "⛅ 多云，14-23°C",
        "武汉": "🌤️ 晴转多云，15-25°C",
        "西安": "☀️ 晴天，10-22°C",
    }
    return weathers.get(city, f"{city} 天气未知")


@tool(name="calculator", description="简单计算器", parameters={
    "type": "object",
    "properties": {
        "expression": {"type": "string", "description": "数学表达式，如 2+3*4"}
    }
})
def calc(expression: str) -> str:
    """计算数学表达式"""
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"计算错误: {e}"


@tool(name="time", description="获取当前时间", parameters={
    "type": "object",
    "properties": {}
})
def get_time() -> str:
    """返回当前日期和时间"""
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


@tool(name="greet", description="生成问候语", parameters={
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "被问候者的名字"},
        "style": {"type": "string", "description": "问候风格：formal（正式）, casual（随意）, friendly（友好）", "default": "friendly"}
    },
    "required": ["name"]
})
def greet(name: str, style: str = "friendly") -> str:
    """生成问候语"""
    greetings = {
        "formal": f"您好，{name}。很高兴为您服务。",
        "casual": f"嘿 {name}，最近怎么样？",
        "friendly": f"你好 {name}！今天过得怎么样？😊"
    }
    return greetings.get(style, greetings["friendly"])
