#!/usr/bin/env python3
"""
Artemis 双通道视觉系统
支持本地（Ollama）和云端（OpenRouter）两种视觉识别通道

核心设计：
- 轻量任务 → 本地 Ollama（免费、快速、隐私优先）
- 精细任务 → OpenRouter gpt-4o-mini（精准、按量计费）
- 自动根据任务复杂度选择通道
"""

import os
import sys
import json
import base64
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Literal
from dataclasses import dataclass
from enum import Enum


# ==================== 配置 ====================

@dataclass
class VisionConfig:
    """视觉通道配置"""
    # 云端通道
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # 本地通道
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llava:7b"  # 或 moondream, qwen2.5-vlm
    ollama_available: bool = False

    # 路由策略
    auto_select: bool = True
    force_channel: Optional[Literal["local", "cloud"]] = None


class VisionChannel(Enum):
    """视觉通道"""
    LOCAL = "local"      # 本地 Ollama
    CLOUD = "cloud"      # OpenRouter
    SKIP = "skip"        # 跳过（无图片）


# ==================== 向量相似度（不用外部库） ====================

def _simple_text_similarity(text1: str, text2: str) -> float:
    """
    简单的文本相似度（词频 cosine）
    用于判断图片描述是否相关
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


# ==================== 核心视觉引擎 ====================

class VisionEngine:
    """
    Artemis 双通道视觉系统

    使用方式：
        engine = VisionEngine(config)
        result = await engine.analyze(
            image_path="/path/to/image.jpg",
            question="这张图里有什么？",
            complexity="medium"  # simple/medium/complex
        )
    """

    def __init__(self, config: Optional[VisionConfig] = None):
        self.config = config or VisionConfig()
        self._check_ollama()

    def _check_ollama(self):
        """检查 Ollama 是否可用"""
        try:
            import urllib.request
            req = urllib.request.urlopen(
                self.config.ollama_base_url + "/api/tags",
                timeout=2
            )
            if req.status == 200:
                self.config.ollama_available = True
        except:
            self.config.ollama_available = False

    def select_channel(
        self,
        complexity: str,
        has_medical_content: bool = False
    ) -> VisionChannel:
        """
        根据任务复杂度选择视觉通道

        简单/日常任务 → 本地 Ollama（快速）
        医学/精细任务 → OpenRouter（精准）
        """
        if self.config.force_channel:
            return VisionChannel.CLOUD if self.config.force_channel == "cloud" else VisionChannel.LOCAL

        # 医学相关内容建议直接用云端
        if has_medical_content:
            return VisionChannel.CLOUD

        # 按复杂度选择
        if complexity == "simple":
            return VisionChannel.LOCAL if self.config.ollama_available else VisionChannel.CLOUD
        elif complexity in ("medium", "complex", "critical"):
            return VisionChannel.CLOUD
        else:
            return VisionChannel.LOCAL if self.config.ollama_available else VisionChannel.CLOUD

    def _load_image_as_base64(self, image_path: str) -> Tuple[str, str]:
        """
        加载图片为 base64，返回 (data_url, mime_type)
        支持本地文件路径
        """
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(f"图片不存在: {image_path}")

        # 读取图片
        with open(path, "rb") as f:
            image_data = f.read()

        # 检测 MIME 类型
        if path.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif path.suffix.lower() == ".png":
            mime = "image/png"
        elif path.suffix.lower() == ".webp":
            mime = "image/webp"
        elif path.suffix.lower() == ".gif":
            mime = "image/gif"
        else:
            mime = "image/jpeg"  # 默认

        b64 = base64.b64encode(image_data).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        return data_url, mime

    def _call_cloud_vision(
        self,
        image_data_url: str,
        question: str,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        调用 OpenRouter 视觉 API
        gpt-4o-mini 支持视觉输入
        """
        import urllib.request
        import urllib.error

        api_key = self.config.openrouter_api_key
        if not api_key:
            return {"success": False, "error": "未配置 OpenRouter API Key"}

        model = model or self.config.openrouter_model
        url = self.config.openrouter_base_url + "/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url}
                        },
                        {
                            "type": "text",
                            "text": question
                        }
                    ]
                }
            ],
            "max_tokens": 1024
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            content = result["choices"][0]["message"]["content"]
            return {
                "success": True,
                "content": content,
                "model": model,
                "channel": "cloud",
                "usage": result.get("usage", {})
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            return {"success": False, "error": f"HTTP {e.code}: {error_body[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _call_local_vision(
        self,
        image_path: str,
        question: str
    ) -> Dict[str, Any]:
        """
        调用本地 Ollama 视觉 API
        支持 llava 和 moondream 模型
        """
        import urllib.request
        import urllib.error

        if not self.config.ollama_available:
            return {"success": False, "error": "Ollama 不可用"}

        url = self.config.ollama_base_url + "/api/generate"

        # 读取图片作为 base64
        try:
            with open(image_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("ascii")
        except Exception as e:
            return {"success": False, "error": f"读取图片失败: {e}"}

        payload = {
            "model": self.config.ollama_model,
            "prompt": question,
            "images": [image_b64],
            "stream": False
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            return {
                "success": True,
                "content": result.get("response", ""),
                "model": self.config.ollama_model,
                "channel": "local",
                "usage": {}
            }
        except urllib.error.HTTPError as e:
            return {"success": False, "error": f"Ollama HTTP {e.code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def analyze(
        self,
        image_path: str,
        question: str,
        complexity: str = "medium",
        channel: Optional[VisionChannel] = None
    ) -> Dict[str, Any]:
        """
        主分析接口

        Args:
            image_path: 图片路径（本地文件）
            question: 分析问题
            complexity: 任务复杂度 (simple/medium/complex)
            channel: 强制指定通道

        Returns:
            {"success": bool, "content": str, "channel": str, ...}
        """
        # 判断是否包含医学内容（需要更高精度）
        medical_keywords = ["ct", "mri", "x光", "x线", "超声", "影像",
                           "片子", "诊断", "病灶", "肿瘤", "骨折"]
        has_medical = any(kw in question.lower() for kw in medical_keywords)

        # 选择通道
        if channel is None:
            channel = self.select_channel(complexity, has_medical)

        # 加载图片
        try:
            data_url, mime = self._load_image_as_base64(image_path)
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}

        # 执行分析
        if channel == VisionChannel.LOCAL:
            print(f"[Vision] 使用本地通道: {self.config.ollama_model}")
            result = self._call_local_vision(image_path, question)

            # 本地失败时自动升级到云端
            if not result["success"] and self.config.openrouter_api_key:
                print("[Vision] 本地失败，升级到云端...")
                result = self._call_cloud_vision(data_url, question)
                channel = VisionChannel.CLOUD

        elif channel == VisionChannel.CLOUD:
            print(f"[Vision] 使用云端通道: {self.config.openrouter_model}")
            result = self._call_cloud_vision(data_url, question)

            # 云端失败时降级到本地（如果有本地可用）
            if not result["success"] and self.config.ollama_available:
                print("[Vision] 云端失败，降级到本地通道...")
                result = self._call_local_vision(image_path, question)
                channel = VisionChannel.LOCAL

        else:
            result = {"success": False, "error": "未知通道"}

        result["selected_channel"] = channel.value
        return result

    def quick_ocr(self, image_path: str) -> Dict[str, Any]:
        """
        快速 OCR 识别图片中的文字
        优先使用本地通道
        """
        return self.analyze(
            image_path=image_path,
            question="请提取图片中所有文字，保持原有格式。",
            complexity="simple"
        )

    def medical_image_analysis(self, image_path: str, context: str = "") -> Dict[str, Any]:
        """
        医学影像分析
        强制使用云端精细分析
        """
        question = "你是一位专业放射科医生。请详细分析这张医学影像：\n"
        if context:
            question += f"\n背景信息：{context}\n"
        question += "\n请提供：1) 影像描述 2) 主要发现 3) 可能的诊断方向 4) 建议进一步检查"

        return self.analyze(
            image_path=image_path,
            question=question,
            complexity="complex",
            channel=VisionChannel.CLOUD
        )


# ==================== 便捷函数 ====================

def create_vision_engine(
    openrouter_key: str = "",
    force_channel: Optional[Literal["local", "cloud"]] = None
) -> VisionEngine:
    """创建视觉引擎，自动从环境变量读取配置"""
    # 尝试从环境变量读取
    key = openrouter_key or os.getenv("OPENROUTER_API_KEY", "")
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_VISION_MODEL", "llava:7b")

    config = VisionConfig(
        openrouter_api_key=key,
        openrouter_model="openai/gpt-4o-mini",
        force_channel=force_channel
    )
    config.ollama_base_url = ollama_url
    config.ollama_model = ollama_model

    return VisionEngine(config)


# ==================== 测试 ====================

if __name__ == "__main__":
    print("Artemis Vision Engine - 双通道视觉系统")
    print("=" * 40)

    engine = create_vision_engine()

    print(f"Ollama 可用: {engine.config.ollama_available}")
    print(f"OpenRouter Key: {'已配置' if engine.config.openrouter_api_key else '未配置'}")
    print()

    # 测试通道选择
    for complexity in ["simple", "medium", "complex"]:
        ch = engine.select_channel(complexity)
        print(f"复杂度 {complexity} → {ch.value}")

    print()
    print("使用示例：")
    print("  result = engine.analyze('/path/to/image.jpg', '这张图里有什么？')")
    print("  result = engine.quick_ocr('/path/to/image.jpg')")
    print("  result = engine.medical_image_analysis('/path/to/xray.jpg', '老年男性，胸痛')")
