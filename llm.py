"""
Artemis LLM Client - Multi-model LLM client supporting MiniMax, OpenRouter, DeepSeek, Anthropic, and Google Gemini.
"""

import os
import json
import base64
import time
import logging
import httpx
from typing import Dict, Any, Optional, List, Iterator
from datetime import datetime

logger = logging.getLogger("artemis.llm")

# Provider configurations
PROVIDERS = {
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "models": ["abab6.5s-chat", "abab6.5-chat", "gemma-7b"],
        "supports_vision": False,
        "supports_function_call": True,
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "anthropic/claude-3-haiku",
            "deepseek/deepseek-chat-v3-0324",
            "google/gemini-2.0-flash",
        ],
        "supports_vision": True,
        "supports_function_call": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-coder"],
        "supports_vision": False,
        "supports_function_call": True,
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "models": [
            "claude-3-5-haiku-20241107",
            "claude-3-opus-4-5-20241120",
            "claude-3-sonnet-4-20250514",
        ],
        "supports_vision": True,
        "supports_function_call": False,
    },
    "google": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "supports_vision": True,
        "supports_function_call": True,
    },
}

# Default models for each provider
DEFAULT_MODELS = {
    "minimax": "abab6.5s-chat",
    "openrouter": "openai/gpt-4o-mini",
    "deepseek": "deepseek-chat",
    "anthropic": "claude-3-sonnet-4-20250514",
    "google": "gemini-2.0-flash",
}


def load_env_file(env_path: str = "/root/.hermes/.env") -> Dict[str, str]:
    """Manually parse .env file (no python-dotenv dependency)."""
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars


class LLMClient:
    """Unified LLM client supporting multiple providers."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize LLM client.
        
        Args:
            config: Optional configuration dict. If not provided, loads from ~/.hermes/.env
        """
        self.config = config or {}
        self.env_vars = load_env_file()
        
        # Load API keys from env
        self.api_keys = {
            "minimax": self.env_vars.get("MINIMAX_API_KEY", ""),
            "openrouter": self.env_vars.get("OPENROUTER_API_KEY", ""),
            "deepseek": self.env_vars.get("DEEPSEEK_API_KEY", ""),
            "anthropic": self.env_vars.get("ANTHROPIC_API_KEY", ""),
            "google": self.env_vars.get("GEMINI_API_KEY", ""),
        }
        
        # Override with config values if provided
        for provider, key_name in [
            ("minimax", "minimax_api_key"),
            ("openrouter", "openrouter_api_key"),
            ("deepseek", "deepseek_api_key"),
            ("anthropic", "anthropic_api_key"),
            ("google", "gemini_api_key"),
        ]:
            if key_name in self.config:
                self.api_keys[provider] = self.config[key_name]
        
        # Initialize httpx clients
        self.clients: Dict[str, httpx.Client] = {}
        self.timeout = httpx.Timeout(self.config.get("timeout", 60.0))
        
        for provider in PROVIDERS:
            if self.api_keys.get(provider):
                base_url = PROVIDERS[provider]["base_url"]
                self.clients[provider] = httpx.Client(
                    base_url=base_url,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
    
    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider is available (has API key and client)."""
        return provider in self.clients and bool(self.api_keys.get(provider))
    
    def get_available_providers(self) -> List[str]:
        """Get list of available providers."""
        return [p for p in self.clients if self.is_provider_available(p)]
    
    def _auto_select_provider(
        self, prompt: str, model: Optional[str] = None, image: Optional[str] = None
    ) -> str:
        """
        Auto-select provider based on task requirements.
        
        Args:
            prompt: The prompt text
            model: Optional model preference
            image: Optional base64 image
            
        Returns:
            Selected provider name
        """
        # If image is provided, need vision-capable provider
        if image:
            for provider in ["openrouter", "anthropic", "google"]:
                if self.is_provider_available(provider):
                    return provider
            # Fallback to openrouter if no vision provider available
            return "openrouter"
        
        # Check prompt complexity
        prompt_lower = prompt.lower()
        
        # Deep reasoning keywords
        reasoning_keywords = [
            "think", "analyze", "reason", "explain", "why", "how",
            "compare", "evaluate", "consider", "reasoning", "logic"
        ]
        is_complex = any(kw in prompt_lower for kw in reasoning_keywords)
        
        # Code-related tasks
        code_keywords = [
            "code", "python", "javascript", "function", "class",
            "implement", "algorithm", "debug", "programming"
        ]
        is_coding = any(kw in prompt_lower for kw in code_keywords)
        
        # Auto-select logic
        if is_complex and not is_coding:
            # Deep reasoning - try claude or deepseek first
            if self.is_provider_available("anthropic"):
                return "anthropic"
            elif self.is_provider_available("openrouter"):
                return "openrouter"
            elif self.is_provider_available("deepseek"):
                return "deepseek"
        
        if is_coding:
            # Coding tasks - deepseek is good for this
            if self.is_provider_available("deepseek"):
                return "deepseek"
            elif self.is_provider_available("openrouter"):
                return "openrouter"
        
        # Default to minimax for simple tasks
        if self.is_provider_available("minimax"):
            return "minimax"
        elif self.is_provider_available("openrouter"):
            return "openrouter"
        
        # Last resort
        available = self.get_available_providers()
        return available[0] if available else "minimax"
    
    def _build_minimax_request(
        self, prompt: str, model: str, system_prompt: Optional[str] = None, image: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build request payload for MiniMax API."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        content = prompt
        if image:
            # MiniMax doesn't support vision, but we handle gracefully
            content = f"[Image attached] {prompt}"
        
        messages.append({"role": "user", "content": content})
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        return payload
    
    def _build_openai_request(
        self, prompt: str, model: str, system_prompt: Optional[str] = None, image: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build request payload for OpenAI-compatible API (OpenRouter, DeepSeek)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        if image:
            # Handle base64 image
            if image.startswith("data:"):
                # Extract mime type and base64 data
                header, data = image.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
            else:
                data = image
                mime_type = "image/jpeg"
            
            content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{data}"},
                },
            ]
        else:
            content = prompt
        
        messages.append({"role": "user", "content": content})
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        return payload
    
    def _build_anthropic_request(
        self, prompt: str, model: str, system_prompt: Optional[str] = None, image: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build request payload for Anthropic Claude API."""
        messages = []
        
        if image:
            # Extract base64 data from data URL
            if image.startswith("data:"):
                header, data = image.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
            else:
                data = image
                mime_type = "image/jpeg"
            
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": data,
                    },
                },
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        
        messages.append({"role": "user", "content": content})
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        return payload
    
    def _build_google_request(
        self, prompt: str, model: str, system_prompt: Optional[str] = None, image: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build request payload for Google Gemini API."""
        contents = []
        
        if image:
            # Extract base64 data
            if image.startswith("data:"):
                header, data = image.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
            else:
                data = image
                mime_type = "image/jpeg"
            
            contents.append({
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": data,
                        }
                    },
                ]
            })
        else:
            parts = [{"text": prompt}]
            if system_prompt:
                # Gemini uses system instruction differently
                contents.append({"role": "user", "parts": parts})
                # Return special format with system instruction
                return {
                    "contents": [{"role": "model", "parts": [{"text": ""}]}],
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
                }
        
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
        }
        
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
        
        return payload
    
    def _get_headers(self, provider: str) -> Dict[str, str]:
        """Get headers for specific provider."""
        headers = {"Content-Type": "application/json"}
        
        if provider == "minimax":
            headers["Authorization"] = f"Bearer {self.api_keys.get('minimax', '')}"
        elif provider == "openrouter":
            headers["Authorization"] = f"Bearer {self.api_keys.get('openrouter', '')}"
            headers["HTTP-Referer"] = "https://artemis.local"
            headers["X-Title"] = "Artemis"
        elif provider == "deepseek":
            headers["Authorization"] = f"Bearer {self.api_keys.get('deepseek', '')}"
        elif provider == "anthropic":
            headers["x-api-key"] = self.api_keys.get("anthropic", "")
            headers["anthropic-version"] = "2023-06-01"
        elif provider == "google":
            # Google uses API key in URL query param instead
            pass
        
        return headers
    
    def _get_endpoint(self, provider: str, model: str) -> str:
        """Get the API endpoint for the provider."""
        if provider == "anthropic":
            return "/messages"
        elif provider == "google":
            return f"/models/{model}:generateContent"
        else:
            return "/chat/completions"
    
    def _chat_with_retry(
        self,
        provider: str,
        model: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Execute chat request with retry (3次指数退避)。
        适用于所有 provider。
        """
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                client = self.clients[provider]
                endpoint = self._get_endpoint(provider, model)
                url = endpoint

                if provider == "google":
                    api_key = self.api_keys.get("google", "")
                    url = f"{client.base_url}{endpoint}?key={api_key}"
                    response = client.post(url, json=payload, headers=headers)
                else:
                    response = client.post(url, json=payload, headers=headers)

                # 5xx / 429 / 超时 → 重试
                if response.status_code >= 500 or response.status_code == 429:
                    wait_time = (2 ** attempt) * 1.5
                    logger.info(
                        "Provider %s HTTP %d，重试 %d/%d，等待 %.1fs",
                        provider, response.status_code, attempt + 1, max_retries, wait_time
                    )
                    time.sleep(wait_time)
                    last_error = f"HTTP {response.status_code}"
                    continue

                # 4xx (非429) → 不重试，直接失败
                if response.status_code == 400:
                    return {
                        "success": False,
                        "content": "",
                        "provider": provider,
                        "model": model,
                        "usage": {},
                        "error": f"Bad request (400): {response.text[:200]}",
                    }

                if response.status_code != 200:
                    return {
                        "success": False,
                        "content": "",
                        "provider": provider,
                        "model": model,
                        "usage": {},
                        "error": f"HTTP {response.status_code}: {response.text[:200]}",
                    }

                # 成功解析响应
                return self._parse_response(provider, model, response.json())

            except httpx.TimeoutException:
                wait_time = (2 ** attempt) * 1.5
                logger.info("Provider %s 超时，重试 %d/%d，等待 %.1fs",
                            provider, attempt + 1, max_retries, wait_time)
                time.sleep(wait_time)
                last_error = "Timeout"
                continue
            except Exception as e:
                last_error = str(e)
                break

        # 全部重试均失败
        return {
            "success": False,
            "content": "",
            "provider": provider,
            "model": model,
            "usage": {},
            "error": f"Request failed after {max_retries} retries: {last_error}",
        }

    def _parse_response(self, provider: str, model: str, data: Dict) -> Dict[str, Any]:
        """解析 provider 响应"""
        content = ""
        usage = {}
        message_data = {}
        tool_calls_result = []

        if provider == "anthropic":
            content = data.get("content", [{}])[0].get("text", "")
            usage = {
                "input_tokens": data.get("usage", {}).get("input_tokens", 0),
                "output_tokens": data.get("usage", {}).get("output_tokens", 0),
            }
            for block in data.get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls_result.append({
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {}),
                    })
        elif provider == "google":
            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            usage = {
                "prompt_tokens": data.get("usageMetadata", {}).get("promptTokenCount", 0),
                "completion_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount", 0),
                "total_tokens": data.get("usageMetadata", {}).get("totalTokenCount", 0),
            }
        else:
            # OpenAI-compatible
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            usage = data.get("usage", {})
            message_data = message
            tool_calls_result = message.get("tool_calls", [])

        return {
            "success": True,
            "content": content,
            "provider": provider,
            "model": model,
            "usage": usage,
            "tool_calls": tool_calls_result,
            "message_data": message_data,
        }

    def chat(
        self,
        prompt: str = None,
        provider: str = "auto",
        model: Optional[str] = None,
        image: Optional[str] = None,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        messages: List[Dict] = None,
        tools: List[Dict] = None,
        _fallback: bool = False,  # 内部标志：是否处于 fallback 模式
    ) -> Dict[str, Any]:
        """
        Unified chat interface.
        
        Args:
            prompt: The user's prompt (used if messages not provided)
            provider: Provider to use ("auto", "minimax", "openrouter", "deepseek", "anthropic", "google")
            model: Optional specific model to use
            image: Optional base64-encoded image (data URL or raw base64)
            system_prompt: Optional system prompt (used if messages not provided)
            stream: Whether to use streaming (currently returns full response)
            messages: NEW: Pre-built message list (takes precedence over prompt/system_prompt)
            tools: NEW: Function calling tools list (OpenAI format)
            
        Returns:
            Dict with keys: success (bool), content (str), provider (str), model (str), 
                          usage (dict), error (str, optional), message_data (dict, optional)
        """
        # Auto-select provider if needed
        if provider == "auto":
            provider = self._auto_select_provider(prompt or "", model, image)
        
        # Check provider availability
        if not self.is_provider_available(provider):
            return {
                "success": False,
                "content": "",
                "provider": provider,
                "model": model or "unknown",
                "usage": {},
                "error": f"Provider '{provider}' is not available (missing API key)",
            }
        
        # Check vision support
        if image and not PROVIDERS[provider]["supports_vision"]:
            return {
                "success": False,
                "content": "",
                "provider": provider,
                "model": model or "unknown",
                "usage": {},
                "error": f"Provider '{provider}' does not support vision",
            }
        
        # Select model
        if model is None:
            model = DEFAULT_MODELS.get(provider, PROVIDERS[provider]["models"][0])
        
        # Build request based on provider
        try:
            # If messages provided, use them directly (caller controls the conversation)
            if messages is not None:
                # Inject image into last user message if provided
                if image:
                    # Find last user message and update it
                    for msg in reversed(messages):
                        if msg.get("role") == "user":
                            content = msg.get("content", "")
                            if isinstance(content, str):
                                msg["content"] = [
                                    {"type": "text", "text": content},
                                    {"type": "image_url", "image_url": {"url": image}}
                                ]
                            break
                
                if provider == "minimax":
                    # MiniMax uses function call format
                    payload = {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                    }
                elif provider == "openrouter":
                    payload = {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                    }
                    if tools:
                        payload["tools"] = tools
                        payload["tool_choice"] = "auto"
                elif provider == "deepseek":
                    payload = {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                    }
                    if tools:
                        payload["tools"] = tools
                elif provider == "anthropic":
                    # Anthropic uses different format
                    msgs_anthropic = [m for m in messages if m.get("role") != "system"]
                    sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
                    payload = {
                        "model": model,
                        "messages": msgs_anthropic,
                        "max_tokens": 4096,
                    }
                    if sys_msg:
                        payload["system"] = sys_msg
                elif provider == "google":
                    # Google Gemini format
                    contents = [m for m in messages if m.get("role") == "user"]
                    payload = {
                        "contents": contents,
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
                    }
            else:
                # Original behavior: build from prompt + system_prompt
                if provider == "minimax":
                    payload = self._build_minimax_request(prompt, model, system_prompt, image)
                elif provider == "openrouter":
                    payload = self._build_openai_request(prompt, model, system_prompt, image)
                elif provider == "deepseek":
                    payload = self._build_openai_request(prompt, model, system_prompt, image)
                elif provider == "anthropic":
                    payload = self._build_anthropic_request(prompt, model, system_prompt, image)
                elif provider == "google":
                    payload = self._build_google_request(prompt, model, system_prompt, image)
                else:
                    return {
                        "success": False,
                        "content": "",
                        "provider": provider,
                        "model": model,
                        "usage": {},
                        "error": f"Unknown provider: {provider}",
                    }
                
                # Add tools if provided (even for prompt-based calls)
                if tools and provider in ["openrouter", "deepseek"]:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"
            
            # NOTE: streaming not yet implemented - always False
            payload["stream"] = False

            # Get headers
            headers = self._get_headers(provider)

            # 使用重试机制执行请求
            result = self._chat_with_retry(provider, model, payload, headers)

            # 如果成功或是从 fallback 模式传来，直接返回
            if result["success"] or _fallback:
                return result

            # 模型降级：尝试其他可用 provider
            # 优先级：MiniMax → OpenRouter → DeepSeek → Anthropic
            fallback_order = ["openrouter", "deepseek", "anthropic", "google"]
            tried = {provider}

            for fb_provider in fallback_order:
                if fb_provider in tried:
                    continue
                if not self.is_provider_available(fb_provider):
                    continue
                # vision 任务只能fallback到支持vision的provider
                if image and not PROVIDERS[fb_provider].get("supports_vision"):
                    continue
                tried.add(fb_provider)
                logger.info("Provider %s 失败，尝试 fallback 到 %s", provider, fb_provider)
                fb_model = model  # 沿用原 model，也可以用对应 provider 的 default
                fb_payload = self._build_payload_for_provider(
                    fb_provider, prompt, model or DEFAULT_MODELS.get(fb_provider), system_prompt, image, messages, tools
                )
                fb_headers = self._get_headers(fb_provider)
                fb_result = self._chat_with_retry(fb_provider, fb_model, fb_payload, fb_headers)
                if fb_result["success"]:
                    fb_result["fallback_from"] = provider
                    return fb_result

            # 全部失败
            return result

        except httpx.TimeoutException:
            return {
                "success": False,
                "content": "",
                "provider": provider,
                "model": model,
                "usage": {},
                "error": "Request timed out (after retries)",
            }
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "provider": provider,
                "model": model,
                "usage": {},
                "error": f"Error: {str(e)}",
            }

    def _build_payload_for_provider(
        self, provider: str, prompt: str, model: str,
        system_prompt: Optional[str], image: Optional[str],
        messages: Optional[List[Dict]], tools: Optional[List[Dict]]
    ) -> Dict[str, Any]:
        """为指定 provider 构建请求 payload（供 fallback 使用）"""
        if messages is not None:
            # 使用已有的 messages
            if provider == "minimax":
                return {"model": model, "messages": messages, "stream": False}
            elif provider in ["openrouter", "deepseek"]:
                payload = {"model": model, "messages": messages, "stream": False}
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"
                return payload
            elif provider == "anthropic":
                msgs = [m for m in messages if m.get("role") != "system"]
                sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
                payload = {"model": model, "messages": msgs, "max_tokens": 4096}
                if sys_msg:
                    payload["system"] = sys_msg
                return payload
            elif provider == "google":
                contents = [m for m in messages if m.get("role") == "user"]
                return {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
        else:
            if provider == "minimax":
                return self._build_minimax_request(prompt, model, system_prompt, image)
            elif provider in ["openrouter", "deepseek"]:
                return self._build_openai_request(prompt, model, system_prompt, image)
            elif provider == "anthropic":
                return self._build_anthropic_request(prompt, model, system_prompt, image)
            elif provider == "google":
                return self._build_google_request(prompt, model, system_prompt, image)
        return {}
    
    def chat_stream(
        self,
        prompt: str,
        provider: str = "auto",
        model: Optional[str] = None,
        image: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Streaming version of chat.
        
        Yields partial responses as they come in.
        Each yield is a dict with: success, content (partial), provider, model, done (bool)
        """
        # Auto-select provider if needed
        if provider == "auto":
            provider = self._auto_select_provider(prompt, model, image)
        
        # Check provider availability
        if not self.is_provider_available(provider):
            yield {
                "success": False,
                "content": "",
                "provider": provider,
                "model": model or "unknown",
                "done": True,
                "error": f"Provider '{provider}' is not available (missing API key)",
            }
            return
        
        # Select model
        if model is None:
            model = DEFAULT_MODELS.get(provider, PROVIDERS[provider]["models"][0])
        
        try:
            # Build request
            if provider == "minimax":
                payload = self._build_minimax_request(prompt, model, system_prompt, image)
            elif provider in ["openrouter", "deepseek"]:
                payload = self._build_openai_request(prompt, model, system_prompt, image)
            elif provider == "anthropic":
                # Anthropic streaming is different
                payload = self._build_anthropic_request(prompt, model, system_prompt, image)
                payload["stream"] = True
            elif provider == "google":
                payload = self._build_google_request(prompt, model, system_prompt, image)
            else:
                yield {"success": False, "content": "", "provider": provider, "model": model, "done": True, "error": f"Unknown provider: {provider}"}
                return
            
            # For now, simple non-streaming fallback for unsupported cases
            # Full streaming implementation would require SSE parsing
            result = self.chat(prompt, provider, model, image, system_prompt, stream=False)
            result["done"] = True
            yield result
            
        except Exception as e:
            yield {
                "success": False,
                "content": "",
                "provider": provider,
                "model": model,
                "done": True,
                "error": f"Error: {str(e)}",
            }
    
    def count_tokens(self, text: str, provider: str = "auto") -> int:
        """
        Estimate token count for text.
        
        Args:
            text: Text to count tokens for
            provider: Provider to use for token counting
            
        Returns:
            Estimated token count
        """
        # Simple estimation: ~4 chars per token for English, ~2 for Chinese
        if provider == "auto":
            # Try to detect language
            has_chinese = any("\u4e00" <= char <= "\u9fff" for char in text)
            chars_per_token = 2 if has_chinese else 4
        else:
            chars_per_token = 2  # Default to Chinese-friendly estimation
        
        return len(text) // chars_per_token + 1
    
    def health_check(self) -> Dict[str, Any]:
        """
        健康检查：测试所有已配置 provider 的 API 连接。
        
        Returns:
            Dict: 每个 provider 的状态 {provider: {available, latency_ms, error}}
        """
        import time
        results = {}

        for provider in PROVIDERS:
            if not self.api_keys.get(provider):
                results[provider] = {"available": False, "latency_ms": None, "error": "No API key"}
                continue

            start = time.time()
            try:
                # 构建最简单的测试请求
                test_payload = {
                    "model": DEFAULT_MODELS.get(provider, PROVIDERS[provider]["models"][0]),
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": False,
                    "max_tokens": 5,
                }

                client = self.clients.get(provider)
                if not client:
                    # 需要先初始化 client
                    base_url = PROVIDERS[provider]["base_url"]
                    client = httpx.Client(base_url=base_url, timeout=10.0)
                    self.clients[provider] = client

                endpoint = self._get_endpoint(provider, test_payload["model"])
                headers = self._get_headers(provider)

                if provider == "google":
                    api_key = self.api_keys.get("google", "")
                    url = f"{client.base_url}{endpoint}?key={api_key}"
                    response = client.post(url, json=test_payload, headers=headers)
                else:
                    response = client.post(endpoint, json=test_payload, headers=headers)

                latency = (time.time() - start) * 1000

                if response.status_code == 200:
                    results[provider] = {"available": True, "latency_ms": round(latency, 1), "error": None}
                else:
                    results[provider] = {
                        "available": False,
                        "latency_ms": round(latency, 1),
                        "error": f"HTTP {response.status_code}",
                    }
            except httpx.TimeoutException:
                results[provider] = {"available": False, "latency_ms": None, "error": "Timeout"}
            except Exception as e:
                results[provider] = {"available": False, "latency_ms": None, "error": str(e)[:80]}

        return results
        """Close all HTTP clients."""
        for client in self.clients.values():
            client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# Convenience function for quick usage
def create_client(config: Optional[Dict[str, Any]] = None) -> LLMClient:
    """Create and return an LLMClient instance."""
    return LLMClient(config)


if __name__ == "__main__":
    # Quick test
    client = LLMClient()
    print(f"Available providers: {client.get_available_providers()}")
    
    # Test simple chat
    result = client.chat("Hello, how are you?", provider="minimax")
    print(f"Result: {result}")
