"""测试 llm.py - LLM 客户端（mock 测试，不调用真实 API）"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from llm import LLMClient, PROVIDERS, DEFAULT_MODELS


@pytest.fixture
def mock_llm_client():
    """创建 LLM 客户端（mock 环境变量）"""
    with patch("llm.load_env_file", return_value={
        "MINIMAX_API_KEY": "test_minimax_key_12345",
        "OPENROUTER_API_KEY": "test_openrouter_key_67890",
        "ANTHROPIC_API_KEY": "test_anthropic_key",
        "DEEPSEEK_API_KEY": "test_deepseek_key",
        "GEMINI_API_KEY": "test_google_key",  # 注意：是 GEMINI_API_KEY
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
    }):
        config = {"timeout": 60.0}
        client = LLMClient(config)
        return client


@pytest.fixture
def llm_client():
    """创建 LLM 客户端（使用真实环境变量，仅用于不需要 keys 的测试）"""
    config = {"timeout": 60.0}
    return LLMClient(config)


class TestLLMClient:
    def test_is_provider_available(self, mock_llm_client):
        """检查 provider 可用性"""
        client = mock_llm_client
        assert client.is_provider_available("minimax") is True
        assert client.is_provider_available("openrouter") is True
        assert client.is_provider_available("anthropic") is True
        assert client.is_provider_available("deepseek") is True
        assert client.is_provider_available("google") is True

    def test_get_available_providers(self, mock_llm_client):
        """获取可用 provider 列表"""
        available = mock_llm_client.get_available_providers()
        assert "minimax" in available
        assert "openrouter" in available
        assert "anthropic" in available
        assert "deepseek" in available
        assert "google" in available

    def test_auto_select_minimax_for_simple(self, mock_llm_client):
        """简单任务自动选择 MiniMax"""
        provider = mock_llm_client._auto_select_provider("你好，今天天气怎么样？")
        assert provider == "minimax"

    def test_auto_select_vision_requires_cloud(self, mock_llm_client):
        """带图片的任务需要云端 provider"""
        provider = mock_llm_client._auto_select_provider(
            "描述这张图", image="data:image/png;base64,fake"
        )
        assert provider in ["openrouter", "anthropic", "google"]

    def test_chat_returns_error_for_unavailable_provider(self, mock_llm_client):
        """不可用的 provider 返回错误"""
        result = mock_llm_client.chat(prompt="test", provider="unknown")
        assert result["success"] is False
        assert "not available" in result["error"]

    def test_chat_returns_error_for_vision_without_support(self, mock_llm_client):
        """不支持视觉的 provider 传图片返回错误"""
        result = mock_llm_client.chat(
            prompt="描述图",
            provider="deepseek",
            image="data:image/png;base64,fake"
        )
        assert result["success"] is False
        assert "vision" in result["error"].lower()

    @patch("httpx.Client.post")
    def test_chat_minimax_success(self, mock_post, mock_llm_client):
        """MiniMax 成功调用"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "你好！"}}],
            "usage": {"input_tokens": 10, "output_tokens": 20}
        }
        mock_post.return_value = mock_response

        result = mock_llm_client.chat(prompt="你好", provider="minimax")

        assert result["success"] is True
        assert result["content"] == "你好！"
        assert result["provider"] == "minimax"
        assert result["usage"]["input_tokens"] == 10

    @patch("httpx.Client.post")
    def test_chat_openrouter_success(self, mock_post, mock_llm_client):
        """OpenRouter 成功调用"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 15}
        }
        mock_post.return_value = mock_response

        result = mock_llm_client.chat(prompt="hi", provider="openrouter")

        assert result["success"] is True
        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 5

    @patch("httpx.Client.post")
    def test_chat_rate_limit_handling(self, mock_post, mock_llm_client):
        """429 限流错误处理"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_post.return_value = mock_response

        result = mock_llm_client.chat(prompt="test", provider="openrouter")

        assert result["success"] is False
        assert "429" in result["error"]

    def test_default_models_defined(self):
        """验证所有 provider 都有默认模型"""
        for provider in PROVIDERS:
            assert provider in DEFAULT_MODELS
            assert DEFAULT_MODELS[provider] in PROVIDERS[provider]["models"]

    def test_providers_have_required_fields(self):
        """验证所有 provider 配置有必需字段"""
        for name, cfg in PROVIDERS.items():
            assert "models" in cfg
            assert "supports_vision" in cfg
            assert "supports_function_call" in cfg


class TestStreamingNotImplemented:
    """streaming 参数未实现 - 验证总是返回 False"""

    @patch("httpx.Client.post")
    def test_stream_always_false(self, mock_post, mock_llm_client):
        """验证 streaming 参数被忽略，总是 False"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test"}}],
            "usage": {}
        }
        mock_post.return_value = mock_response

        # 传入 stream=True，但应该被忽略
        result = mock_llm_client.chat(prompt="test", provider="minimax", stream=True)

        # 验证实际发送的是 stream=False
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload.get("stream") is False
