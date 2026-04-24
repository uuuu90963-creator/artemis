"""测试 vision.py - 视觉引擎"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from vision import VisionEngine, VisionChannel, create_vision_engine


@pytest.fixture
def vision_engine(tmp_artemis_home, mock_env):
    """创建视觉引擎（使用测试环境）"""
    engine = VisionEngine()
    return engine


@pytest.fixture
def test_image(tmp_path):
    """创建测试图片"""
    img = tmp_path / "test.png"
    # 创建一个最小的 PNG 文件（1x1 红色像素）
    png_data = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x18, 0xDD,
        0x8D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
        0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ])
    img.write_bytes(png_data)
    return img


class TestVisionEngine:
    def test_init(self, vision_engine):
        """验证初始化"""
        assert vision_engine is not None

    def test_ollama_not_available_by_default(self, vision_engine):
        """Ollama 默认不可用（测试环境）"""
        assert vision_engine.config.ollama_available is False

    def test_select_channel_cloud(self, vision_engine):
        """默认选择云端通道"""
        ch = vision_engine.select_channel("medium", False)
        assert ch == VisionChannel.CLOUD

    def test_select_channel_local_when_forced(self, vision_engine):
        """强制本地通道"""
        engine = create_vision_engine(force_channel="local")
        ch = engine.select_channel("medium", False)
        assert ch == VisionChannel.LOCAL

    def test_load_image_as_base64(self, vision_engine, test_image):
        """加载图片为 base64"""
        data_url, mime = vision_engine._load_image_as_base64(str(test_image))
        assert data_url.startswith("data:image/png;base64,")
        assert mime == "image/png"

    def test_load_image_not_found(self, vision_engine):
        """图片不存在时抛出异常"""
        with pytest.raises(FileNotFoundError):
            vision_engine._load_image_as_base64("/nonexistent/image.png")


class TestVisionFallback:
    """视觉通道降级测试"""

    def test_cloud_to_local_fallback(self, vision_engine, test_image):
        """云端失败时降级到本地"""
        # Mock 云端调用失败
        with patch.object(
            vision_engine, "_call_cloud_vision",
            return_value={"success": False, "error": "API error"}
        ):
            # Mock Ollama 可用
            with patch.object(
                vision_engine.config, "ollama_available", True
            ):
                with patch.object(
                    vision_engine, "_call_local_vision",
                    return_value={"success": True, "content": "本地分析结果"}
                ):
                    result = vision_engine.analyze(
                        image_path=str(test_image),
                        question="描述图片",
                        complexity="medium"
                    )

                    # 应该成功，因为降级到本地
                    assert result["success"] is True
                    assert result["content"] == "本地分析结果"
                    assert result["selected_channel"] == "local"


class TestMedicalImageAnalysis:
    """医学影像分析测试"""

    def test_complexity_detection(self, vision_engine):
        """CT/MRI 等关键词触发复杂模式"""
        # 简单检查：传入医学关键词
        ch = vision_engine.select_channel("complex", True)
        # 复杂医学影像使用云端
        assert ch == VisionChannel.CLOUD


class TestCreateVisionEngine:
    """create_vision_engine 工厂函数测试"""

    def test_create_with_defaults(self, tmp_artemis_home, mock_env):
        """默认创建"""
        engine = create_vision_engine()
        assert engine is not None

    def test_create_with_force_channel(self, tmp_artemis_home, mock_env):
        """强制指定通道"""
        engine = create_vision_engine(force_channel="local")
        assert engine.config.force_channel == "local"

        engine2 = create_vision_engine(force_channel="cloud")
        assert engine2.config.force_channel == "cloud"
