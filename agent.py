#!/usr/bin/env python3
"""
Artemis Agent Loop - 真正的 Agent 执行引擎
支持：工具调用、流式输出、上下文压缩、成本追踪、双通道视觉
"""

import os
import json
import time
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Iterator
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path.home() / ".hermes" / "artemis"

# 导入 Vision Engine（支持 Ollama 本地 + OpenRouter 云端双通道）
try:
    from vision import VisionEngine, VisionChannel, create_vision_engine
    HAS_VISION = True
except ImportError:
    HAS_VISION = False
    VisionEngine = None


# ======== 成本追踪 ========

class CostTracker:
    """追踪真实 API 花费"""
    
    # OpenRouter 参考价格（$/1M tokens）
    OPENROUTER_PRICES = {
        "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "openai/gpt-4o": {"input": 2.50, "output": 10.00},
        "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
        "anthropic/claude-3-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "deepseek/deepseek-chat-v3-0324": {"input": 0.27, "output": 1.10},
        "google/gemini-2.0-flash": {"input": 0.00, "output": 0.00},  # 免费
    }
    
    # MiniMax 参考价格（粗估）
    MINIMAX_PRICES = {
        "abab6.5s-chat": {"input": 0.05, "output": 0.05},
        "abab6.5-chat": {"input": 0.05, "output": 0.05},
    }
    
    def __init__(self, db_path: Path = None):
        self.db_path = db_path or (BASE_DIR / "memories" / "costs.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.session_start = datetime.now()
        self.session_costs: List[Dict] = []
    
    def _init_db(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS cost_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                provider TEXT,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                task_type TEXT,
                session_id TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                started_at TEXT,
                ended_at TEXT,
                total_cost_usd REAL
            )
        """)
        conn.commit()
        conn.close()
    
    def log(self, provider: str, model: str, input_tokens: int, output_tokens: int,
            task_type: str = "unknown", session_id: str = "default"):
        """记录一次 API 调用花费"""
        cost = self.calc_cost(provider, model, input_tokens, output_tokens)
        
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO cost_logs (timestamp, provider, model, input_tokens, output_tokens, cost_usd, task_type, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), provider, model, input_tokens, output_tokens, cost, task_type, session_id))
        conn.commit()
        conn.close()
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost
        }
        self.session_costs.append(entry)
        return cost
    
    def calc_cost(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
        """计算花费（美元）"""
        prices = {}
        if provider == "openrouter":
            prices = self.OPENROUTER_PRICES
        elif provider == "minimax":
            prices = self.MINIMAX_PRICES
        
        model_prices = prices.get(model, {"input": 0.0, "output": 0.0})
        cost = (input_tokens / 1_000_000) * model_prices.get("input", 0)
        cost += (output_tokens / 1_000_000) * model_prices.get("output", 0)
        return round(cost, 6)
    
    def get_session_cost(self) -> float:
        """获取当前会话总花费"""
        return round(sum(e["cost_usd"] for e in self.session_costs), 6)
    
    def get_total_cost(self, days: int = 30) -> Dict[str, Any]:
        """获取历史总花费"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT SUM(cost_usd), SUM(input_tokens), SUM(output_tokens), COUNT(*)
            FROM cost_logs
            WHERE timestamp >= datetime('now', '-' || ? || ' days')
        """, (days,))
        row = c.fetchone()
        conn.close()
        return {
            "total_cost_usd": round(row[0] or 0, 6),
            "total_input_tokens": row[1] or 0,
            "total_output_tokens": row[2] or 0,
            "total_calls": row[3] or 0,
        }
    
    def summary(self) -> str:
        """获取花费摘要"""
        session = self.get_session_cost()
        total = self.get_total_cost(30)
        return (
            f"💰 花费摘要\n"
            f"  本次会话: ${session:.4f}\n"
            f"  近30天: ${total['total_cost_usd']:.4f} ({total['total_calls']} 次调用)\n"
            f"  输入 tokens: {total['total_input_tokens']:,}\n"
            f"  输出 tokens: {total['total_output_tokens']:,}"
        )


# ======== 上下文压缩 ========

class ContextCompressor:
    """对话历史压缩，防止 token 爆表"""
    
    def __init__(self, max_messages: int = 40, max_tokens_per_msg: int = 500):
        self.max_messages = max_messages
        self.max_tokens_per_msg = max_tokens_per_msg
    
    def compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        压缩消息列表，保留最近 N 条和重要的 system 消息
        策略：
        1. 保留所有 system 消息
        2. 保留最近 max_messages 条 user/assistant 消息
        3. 中间的长消息截断
        """
        if len(messages) <= self.max_messages:
            return messages
        
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        
        # 保留最近的消息
        recent = other_msgs[-self.max_messages:]
        
        # 如果中间有特别长的消息，截断
        compressed = []
        for m in recent:
            content = m.get("content", "")
            if isinstance(content, str) and len(content) > self.max_tokens_per_msg * 4:  # ~2000 chars
                m = dict(m)
                m["content"] = content[:self.max_tokens_per_msg * 4] + "\n[...截断...]"
            compressed.append(m)
        
        return system_msgs + compressed
    
    def make_summary_prompt(self, old_messages: List[Dict]) -> str:
        """生成摘要提示词（用于压缩旧消息）"""
        return (
            "请简要总结以下对话的核心内容，保留关键信息（用户需求、关键结论、待办事项）。"
            "回复格式：直接输出摘要，不要加前缀。\n\n"
            + "\n---\n".join(
                f"[{m.get('role', 'unknown')}]: {m.get('content', '')[:300]}"
                for m in old_messages[-20:]
            )
        )


# ======== Agent Loop ========

class ArtemisAgent:
    """
    Artemis Agent 执行引擎
    核心：支持工具调用的多轮对话循环 + 双通道视觉
    """
    
    def __init__(self, llm_client, plugins_manager=None, vision_engine=None):
        self.llm = llm_client
        self.plugins = plugins_manager
        self.cost_tracker = CostTracker()
        self.compressor = ContextCompressor()
        self.max_turns = 10  # 最多 N 轮工具调用，防止死循环
        
        # 视觉引擎（支持 Ollama 本地 + OpenRouter 云端双通道）
        if vision_engine is not None:
            self.vision = vision_engine
        elif HAS_VISION and vision_engine is not False:
            try:
                self.vision = create_vision_engine()
                print(f"[Agent] ✓ 视觉引擎已初始化 (Ollama: {'可用' if self.vision.config.ollama_available else '不可用'})")
            except Exception as e:
                print(f"[Agent] ⚠ 视觉引擎初始化失败: {e}")
                self.vision = None
        else:
            self.vision = None
        
        # 对话历史（当前任务）
        self.messages: List[Dict] = []
    
    def reset(self):
        """重置对话历史"""
        self.messages = []
    
    def _build_messages(self, prompt: str, system_prompt: str, image: str = None,
                       prepend_messages: List[Dict] = None,
                       image_description: str = None) -> List[Dict]:
        """
        构建消息列表
        
        Args:
            prompt: 用户消息
            system_prompt: 系统提示词
            image: 可选的图片路径/URL/base64
            prepend_messages: 追加的历史消息
            image_description: 视觉引擎预处理后的图片描述（当 LLM 不支持 vision 时）
        """
        msgs = []
        
        # System 消息
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        
        # 追加之前的历史（如有）
        if prepend_messages:
            msgs.extend(prepend_messages)
        
        # 用户消息
        if image:
            # 如果有预处理描述，说明 LLM 不支持 vision，用文字描述代替
            if image_description:
                content = (
                    f"[用户上传了一张图片，图片分析结果如下]\n"
                    f"{image_description}\n\n"
                    f"用户的问题是：{prompt}"
                )
                msgs.append({"role": "user", "content": content})
            elif image.startswith("data:") or image.startswith("http"):
                # 云端支持直接传图片
                msgs.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image}}
                    ]
                })
            else:
                # 本地文件路径，需要先读取
                msgs.append({"role": "user", "content": f"[Image: {image}] {prompt}"})
        else:
            msgs.append({"role": "user", "content": prompt})
        
        return msgs
    
    def _get_tools(self) -> List[Dict]:
        """获取当前可用的工具列表"""
        if not self.plugins:
            return []
        return self.plugins.get_all_tools()
    
    def _execute_tool_call(self, tool_name: str, arguments: Dict) -> str:
        """执行单个工具调用"""
        if not self.plugins:
            return f"[错误] 插件系统未初始化"
        
        try:
            # 查找工具
            # 格式可能是 "plugin_name.tool_name" 或直接 "tool_name"
            if "." in tool_name:
                plugin_name, _, actual_tool = tool_name.partition(".")
            else:
                plugin_name = None
                actual_tool = tool_name
            
            if plugin_name:
                result = self.plugins.call_tool(plugin_name, actual_tool, arguments)
            else:
                result = self.plugins.call_tool_global(actual_tool, arguments)
            
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"[工具执行错误] {str(e)}"
    
    def _parse_tool_calls(self, response_content: str, provider: str) -> List[Dict]:
        """从响应中解析工具调用（兼容不同格式）"""
        tool_calls = []
        
        # OpenAI 格式：response 中有 function_call 字段
        if isinstance(response_content, dict):
            if "tool_calls" in response_content:
                for tc in response_content["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_calls.append({
                        "id": tc.get("id", f"call_{len(tool_calls)}"),
                        "name": fn.get("name", ""),
                        "arguments": json.loads(fn.get("arguments", "{}"))
                    })
            return tool_calls
        
        # 纯文本格式：尝试从 markdown 代码块中解析
        # 格式：```json\n{"tool": "xxx", "arguments": {...}}\n```
        if isinstance(response_content, str):
            pattern = r'```(?:json)?\s*\n?(\{"tool":\s*"([^"]+)".*?\})\s*\n?```'
            matches = re.findall(pattern, response_content, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match[0])
                    tool_calls.append({
                        "id": f"call_{len(tool_calls)}",
                        "name": data.get("tool", ""),
                        "arguments": data.get("arguments", {})
                    })
                except:
                    pass
            
            # 也支持不带代码块的格式
            if not tool_calls:
                pattern2 = r'\{"tool":\s*"([^"]+)",\s*"arguments":\s*(\{.*?\})\s*\}'
                matches2 = re.findall(pattern2, response_content, re.DOTALL)
                for name, args_str in matches2:
                    try:
                        tool_calls.append({
                            "id": f"call_{len(tool_calls)}",
                            "name": name,
                            "arguments": json.loads(args_str)
                        })
                    except:
                        pass
        
        return tool_calls
    
    def chat(
        self,
        prompt: str,
        system_prompt: str = "",
        image: str = None,
        tools: List[Dict] = None,
        stream_callback: Callable[[str], None] = None,
        session_id: str = "default",
        context_messages: List[Dict] = None,
    ) -> Dict[str, Any]:
        """
        核心 chat 接口（支持工具调用 + 双通道视觉）
        
        Args:
            prompt: 用户消息
            system_prompt: 系统提示词
            image: 可选的图片路径/URL
            tools: 工具列表（如果为 None，自动从 plugins 获取）
            stream_callback: 流式输出回调，每收到一个 token 就调用
            session_id: 会话 ID（用于成本追踪）
            context_messages: 追加的上下文消息（如之前的对话历史）
        
        Returns:
            {"success": bool, "content": str, "provider": str, "model": str,
             "usage": {}, "tool_calls": [], "total_turns": int, "cost_usd": float}
        """
        # ===== 图片预处理：Vision Engine 双通道 =====
        image_description = None
        processed_image = image  # 最终传给 LLM 的图片
        
        if image and self.vision:
            # 判断任务复杂度（默认 medium）
            # 医学影像相关用复杂模式
            medical_keywords = ["ct", "mri", "x光", "x线", "超声", "影像",
                               "片子", "诊断", "病灶", "肿瘤", "骨折", "心电图"]
            complexity = "complex" if any(kw in prompt.lower() for kw in medical_keywords) else "medium"
            
            try:
                # 使用 VisionEngine 分析图片（自动选择 Ollama 或 OpenRouter）
                vision_result = self.vision.analyze(
                    image_path=image if Path(image).exists() else None,
                    question=prompt,
                    complexity=complexity
                )
                
                if vision_result.get("success"):
                    channel = vision_result.get("selected_channel", "unknown")
                    print(f"[Agent] ✓ 视觉分析完成 (通道: {channel})")
                    
                    # 如果是本地 Ollama 处理，不需要传图片给 LLM 了
                    if channel == "local":
                        image_description = vision_result.get("content", "")
                        processed_image = None  # 不再传图片给 LLM
                    # 云端处理的话，直接传图片给 LLM（LLM 自己看）
                else:
                    print(f"[Agent] ⚠ 视觉分析失败: {vision_result.get('error')}, 尝试备用方案")
                    # fallback: 传图片让 LLM 直接看（如果支持的话）
            except Exception as e:
                print(f"[Agent] ⚠ 视觉预处理异常: {e}")
                # 继续尝试直接传图片给 LLM
        
        # ===== 获取工具 =====
        if tools is None:
            tools = self._get_tools()
        
        # 构建初始消息（传入预处理后的图片描述）
        messages = self._build_messages(prompt, system_prompt, processed_image, image_description=image_description)
        
        # 追加上下文
        if context_messages:
            # 从 context 中移除最早的 system 消息（避免重复）
            ctx = list(context_messages)
            if ctx and ctx[0].get("role") == "system":
                ctx = ctx[1:]
            messages[1:1] = ctx  # 插入到 system 之后
        
        total_turns = 0
        total_cost = 0.0
        all_tool_calls = []
        
        while total_turns < self.max_turns:
            total_turns += 1
            
            # 调用 LLM
            provider = "auto"
            model = None
            
            # 判断用哪个 provider（工具调用最好用 OpenRouter/DeepSeek）
            if tools and total_turns == 1:
                # 第一次调用，如果配置了工具，优先用支持工具的 provider
                available = self.llm.get_available_providers()
                if "openrouter" in available:
                    provider = "openrouter"
                elif "deepseek" in available:
                    provider = "deepseek"
            
            # 调用
            result = self.llm.chat(
                prompt=None,  # 不用了，用 messages
                provider=provider,
                model=model,
                image=image if total_turns == 1 else None,
                system_prompt=None,  # 不用，用 messages
                messages=messages,  # 新参数
                tools=tools if total_turns == 1 else None,  # 只有第一轮给工具
                stream=False,
            )
            
            if not result.get("success"):
                return {
                    "success": False,
                    "content": f"LLM 调用失败: {result.get('error', '未知错误')}",
                    "provider": provider,
                    "model": result.get("model", ""),
                    "usage": {},
                    "tool_calls": all_tool_calls,
                    "total_turns": total_turns,
                    "cost_usd": total_cost,
                }
            
            # 记录成本
            usage = result.get("usage", {})
            input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
            cost = self.cost_tracker.calc_cost(
                result.get("provider", provider),
                result.get("model", ""),
                input_tokens, output_tokens
            )
            total_cost += cost
            self.cost_tracker.log(
                result.get("provider", provider),
                result.get("model", ""),
                input_tokens, output_tokens,
                session_id=session_id
            )
            
            response_content = result.get("content", "")
            
            # 检查是否有工具调用
            # OpenAI/OpenRouter 格式：message 中有 tool_calls
            message_data = result.get("message_data", {})
            if isinstance(response_content, str):
                # 尝试解析工具调用
                tool_calls = self._parse_tool_calls(response_content, provider)
            else:
                tool_calls = []
            
            # 也检查 message_data 中的 tool_calls
            if "tool_calls" in message_data:
                for tc in message_data["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_calls.append({
                        "id": tc.get("id", f"call_{len(tool_calls)}"),
                        "name": fn.get("name", ""),
                        "arguments": json.loads(fn.get("arguments", "{}"))
                    })
            
            if not tool_calls:
                # 没有工具调用，说明是最终回复
                if stream_callback:
                    stream_callback(response_content)
                return {
                    "success": True,
                    "content": response_content,
                    "provider": result.get("provider", provider),
                    "model": result.get("model", ""),
                    "usage": usage,
                    "tool_calls": all_tool_calls,
                    "total_turns": total_turns,
                    "cost_usd": round(total_cost, 6),
                }
            
            # 有工具调用：添加到对话
            assistant_msg = {"role": "assistant", "content": response_content}
            messages.append(assistant_msg)
            all_tool_calls.extend(tool_calls)
            
            # 执行工具
            tool_results = []
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                args = tc.get("arguments", {})
                all_tool_calls[-len(tool_calls) + tool_calls.index(tc)]["result"] = "executing..."
                
                result_str = self._execute_tool_call(tool_name, args)
                
                tool_results.append({
                    "tool_call_id": tc.get("id", ""),
                    "tool_name": tool_name,
                    "result": result_str,
                })
                
                # 添加到消息历史
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": tool_name,
                    "content": result_str,
                })
            
            # 流式输出工具结果
            if stream_callback:
                for tr in tool_results:
                    stream_callback(f"\n[调用工具: {tr['tool_name']}] → {tr['result'][:100]}...\n")
    
    def chat_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        image: str = None,
        tools: List[Dict] = None,
        session_id: str = "default",
    ) -> Iterator[Dict[str, Any]]:
        """
        流式版本 chat
        Yields: {"type": "content"|"tool_call"|"done", "content": str, "data": dict}
        """
        if tools is None:
            tools = self._get_tools()
        
        messages = self._build_messages(prompt, system_prompt, image)
        
        provider = "auto"
        available = self.llm.get_available_providers()
        if "openrouter" in available:
            provider = "openrouter"
        elif "deepseek" in available:
            provider = "deepseek"
        
        # 流式调用
        for chunk in self.llm.chat_stream(
            prompt=None,
            provider=provider,
            model=None,
            image=image,
            system_prompt=None,
            messages=messages,
            tools=tools,
        ):
            yield chunk
            
            if chunk.get("done"):
                break


# ======== 便捷函数 ========

def create_agent(llm_client, plugins_manager=None, vision_engine=None) -> ArtemisAgent:
    """创建 Agent 实例（自动初始化视觉引擎）"""
    return ArtemisAgent(llm_client, plugins_manager, vision_engine=vision_engine)
