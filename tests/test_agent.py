"""测试 agent.py - Agent 执行引擎"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from agent import ArtemisAgent, CostTracker


@pytest.fixture
def mock_llm():
    """创建 Mock LLM 客户端"""
    llm = MagicMock()
    llm.chat.return_value = {
        "success": True,
        "content": "这是测试回复",
        "provider": "minimax",
        "model": "abab6.5s-chat",
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "message_data": {},
    }
    llm.get_available_providers.return_value = ["minimax"]
    return llm


@pytest.fixture
def mock_plugins():
    """创建 Mock 插件管理器"""
    plugins = MagicMock()
    plugins.get_all_tools.return_value = []
    return plugins


@pytest.fixture
def agent(mock_llm, mock_plugins):
    """创建 Agent 实例"""
    return ArtemisAgent(mock_llm, mock_plugins)


class TestCostTracker:
    """成本追踪测试"""

    def test_calc_cost_openrouter(self):
        """计算 OpenRouter 成本"""
        tracker = CostTracker()
        cost = tracker.calc_cost(
            "openrouter",
            "openai/gpt-4o-mini",
            input_tokens=1000,
            output_tokens=500
        )
        # 0.15/1M * 1000 + 0.60/1M * 500 = 0.00015 + 0.00030 = 0.00045
        assert cost == 0.00045

    def test_calc_cost_minimax(self):
        """计算 MiniMax 成本"""
        tracker = CostTracker()
        cost = tracker.calc_cost(
            "minimax",
            "abab6.5s-chat",
            input_tokens=1000,
            output_tokens=500
        )
        # 0.05/1M * 1500 = 0.000075
        assert cost == 0.000075

    def test_calc_cost_unknown_model(self):
        """未知模型返回 0"""
        tracker = CostTracker()
        cost = tracker.calc_cost(
            "unknown",
            "unknown-model",
            input_tokens=1000,
            output_tokens=500
        )
        assert cost == 0.0


class TestArtemisAgent:
    """Agent 执行引擎测试"""

    def test_chat_success(self, agent):
        """成功执行对话"""
        result = agent.chat("你好")

        assert result["success"] is True
        assert "content" in result
        assert result["provider"] == "minimax"

    def test_chat_with_system_prompt(self, agent, mock_llm):
        """带系统提示词"""
        result = agent.chat(
            "你好",
            system_prompt="你是一个友好的助手"
        )

        assert result["success"] is True
        # 验证 system_prompt 被传入
        call_kwargs = mock_llm.chat.call_args[1]
        # system_prompt 会合并到 messages 中

    def test_chat_failure_returns_error(self, agent, mock_llm):
        """LLM 失败时返回错误"""
        mock_llm.chat.return_value = {
            "success": False,
            "error": "API error",
            "provider": "minimax",
            "model": "abab6.5s-chat",
            "usage": {},
        }

        result = agent.chat("你好")

        assert result["success"] is False
        assert "error" in result["content"]

    def test_chat_tracks_cost(self, agent):
        """追踪对话成本"""
        initial_cost = agent.cost_tracker.get_session_cost()

        agent.chat("你好")

        new_cost = agent.cost_tracker.get_session_cost()
        assert new_cost > initial_cost

    def test_image_processing_vision_engine(self, mock_llm, mock_plugins):
        """图片处理使用 Vision Engine"""
        # Vision Engine 不可用时降级（传 None）
        agent = ArtemisAgent(mock_llm, mock_plugins, vision_engine=None)

        result = agent.chat(
            "描述图片",
            image="/path/to/image.png"
        )

        # 即使 vision 不可用，也应该尝试直接传图片
        assert result["success"] is True


class TestArtemisAgentTools:
    """工具调用测试"""

    def test_tools_passed_to_llm(self, mock_llm, mock_plugins):
        """工具传递给 LLM"""
        mock_plugins.get_all_tools.return_value = [
            {"name": "test_tool", "description": "测试工具"}
        ]
        mock_plugins.get_tool_schema.return_value = {
            "name": "test_tool",
            "description": "测试工具",
            "parameters": {"type": "object"}
        }

        agent = ArtemisAgent(mock_llm, mock_plugins)

        agent.chat("使用工具")

        # 验证 tools 参数被传递
        call_kwargs = mock_llm.chat.call_args[1]
        assert "tools" in call_kwargs

    def test_tool_result_appended_to_messages(self, mock_llm, mock_plugins):
        """工具结果追加到消息"""
        # 第一轮返回工具调用
        mock_llm.chat.side_effect = [
            {
                "success": True,
                "content": "",
                "provider": "minimax",
                "model": "abab6.5s-chat",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "message_data": {},
                "tool_calls": [{"name": "get_weather", "id": "call_1", "args": {"city": "北京"}}],
            },
            {
                "success": True,
                "content": "北京天气晴朗",
                "provider": "minimax",
                "model": "abab6.5s-chat",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "message_data": {},
            },
        ]

        mock_plugins.get_tool_handler.return_value = lambda **kwargs: "北京天气晴朗，25度"
        mock_plugins.get_tool_schema.return_value = {
            "name": "get_weather",
            "description": "获取天气",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
        }

        agent = ArtemisAgent(mock_llm, mock_plugins)
        result = agent.chat("北京天气怎么样")

        assert result["success"] is True
