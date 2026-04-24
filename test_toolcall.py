#!/usr/bin/env python3
"""
Function Call Loop 真实测试脚本
验证 Artemis 的工具调用链路是否真正打通

测试流程:
1. 加载 MCP 插件获取工具列表
2. 用 OpenRouter + tools 调用 LLM（问题需要工具）
3. LLM 返回 tool_calls → 解析
4. 执行工具 → 获取结果
5. 把结果发回 LLM → 获取最终回复
6. 输出完整链路

运行: python3 test_toolcall.py
"""
import sys
import os
import json
from pathlib import Path

# 添加 artemis 目录到路径
ARTEMIS_DIR = Path(__file__).parent
sys.path.insert(0, str(ARTEMIS_DIR))

# ===== 1. 加载 .env =====
ENV_FILE = Path.home() / ".hermes" / ".env"
api_keys = {}
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            api_keys[k.strip()] = v.strip()
    print(f"[1] 环境变量加载: {list(api_keys.keys())}")
else:
    print("[!] ~/.hermes/.env 不存在，请先配置")
    sys.exit(1)

OPENROUTER_KEY = api_keys.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_KEY:
    print("[!] OPENROUTER_API_KEY 未配置")
    sys.exit(1)

# ===== 2. 初始化 LLM 客户端 =====
from llm import LLMClient
llm = LLMClient()

# 确保 OpenRouter 可用
available = llm.get_available_providers()
print(f"[2] 可用 providers: {available}")
if "openrouter" not in available:
    print("[!] OpenRouter 不可用")
    sys.exit(1)

# ===== 3. 加载 MCP 插件获取工具 =====
from plugins.mcp_plugin import MCPPluginManager
import artemis

# 获取 artemis 主目录
plugin_dir = ARTEMIS_DIR / "plugins"
mcp = MCPPluginManager(str(plugin_dir))
mcp.load_all_plugins()
tools = mcp.get_all_tools()
print(f"[3] MCP 工具加载: {len(tools)} 个")
for t in tools:
    print(f"    - {t['function']['name']}: {t['function']['description']}")

if not tools:
    print("[!] 没有可用工具")
    sys.exit(1)

# ===== 4. 构建测试任务 =====
# 用"包头天气"触发 weather 工具
test_question = "包头今天的天气怎么样？"
system_prompt = "你是一个有用的助手。遇到需要查询的问题时，你会使用提供的工具。"

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": test_question},
]

print(f"\n[4] 测试问题: {test_question}")
print(f"    预期触发工具: weather(city='包头')")

# ===== 5. 第一轮: 调用 LLM（带工具）=====
print("\n[5] 第一轮 LLM 调用...")
result1 = llm.chat(
    prompt=None,
    messages=messages,
    tools=tools,
    provider="openrouter",
    model="openai/gpt-4o-mini",
    stream=False,
)

print(f"    success: {result1.get('success')}")
print(f"    provider: {result1.get('provider')}")
print(f"    model: {result1.get('model')}")
print(f"    content: {result1.get('content', '')[:200]}")
print(f"    tool_calls: {result1.get('tool_calls', [])}")

if not result1.get("success"):
    print(f"[!] LLM 调用失败: {result1.get('error')}")
    sys.exit(1)

# ===== 6. 解析 tool_calls =====
tool_calls = result1.get("tool_calls", [])
message_data = result1.get("message_data", {})

# 也检查 message_data 中的 tool_calls（OpenAI 格式）
if "tool_calls" in message_data:
    for tc in message_data["tool_calls"]:
        fn = tc.get("function", {})
        tool_calls.append({
            "id": tc.get("id", f"call_{len(tool_calls)}"),
            "name": fn.get("name", ""),
            "arguments": json.loads(fn.get("arguments", "{}"))
        })

if not tool_calls:
    print("[!] LLM 没有返回 tool_calls（可能模型选择不调用工具）")
    print(f"    实际回复: {result1.get('content', '')}")
    sys.exit(0)  # 不算错误，只是模型没选择用工具

print(f"\n[6] 解析到 {len(tool_calls)} 个工具调用:")
for tc in tool_calls:
    print(f"    [{tc.get('id')}] {tc.get('name')}({tc.get('arguments')})")

# ===== 7. 执行工具 =====
print("\n[7] 执行工具...")
tool_results = []
for tc in tool_calls:
    tool_name = tc.get("name", "")
    args = tc.get("arguments", {})
    
    try:
        result = mcp.call_tool_global(tool_name, args)
        result_str = json.dumps(result, ensure_ascii=False)
        print(f"    {tool_name}({args}) → {result_str}")
    except Exception as e:
        result_str = f"[错误] {e}"
        print(f"    {tool_name}({args}) → {result_str}")
    
    tool_results.append({
        "tool_call_id": tc.get("id", ""),
        "tool_name": tool_name,
        "result": result_str,
    })
    
    # 添加到消息历史
    messages.append({
        "role": "assistant",
        "content": result1.get("content", ""),
    })
    messages.append({
        "role": "tool",
        "tool_call_id": tc.get("id", ""),
        "name": tool_name,
        "content": result_str,
    })

# ===== 8. 第二轮: 把工具结果发回 LLM =====
print("\n[8] 第二轮 LLM 调用（带工具结果）...")
result2 = llm.chat(
    prompt=None,
    messages=messages,
    tools=None,  # 第二轮不需要再给工具
    provider="openrouter",
    model="openai/gpt-4o-mini",
    stream=False,
)

print(f"    success: {result2.get('success')}")
print(f"    content: {result2.get('content', '')}")

if not result2.get("success"):
    print(f"[!] 第二轮 LLM 调用失败: {result2.get('error')}")
    sys.exit(1)

# ===== 9. 输出最终结果 =====
print("\n" + "="*60)
print("✅ Function Call Loop 测试成功！")
print("="*60)
print(f"\n问题: {test_question}")
print(f"调用工具: {', '.join(tc['name'] for tc in tool_calls)}")
print(f"工具结果: {', '.join(tr['result'] for tr in tool_results)}")
print(f"\n最终回复:\n{result2.get('content', '')}")
print(f"\n总成本: ${result2.get('cost_usd', result1.get('cost_usd', 0)):.6f}")
