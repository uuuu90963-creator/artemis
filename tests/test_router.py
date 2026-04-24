"""测试 router.py - 任务路由系统"""

import pytest
from router import TaskRouter, TaskType, Complexity


@pytest.fixture
def router():
    """创建路由实例"""
    config = {
        "routing": {
            "text_default": "minimax",
            "vision_primary": "openrouter",
            "vision_fallback": "local",
        }
    }
    return TaskRouter(config)


class TestTaskRouter:
    def test_classify_simple_text(self, router):
        """简单文字分类"""
        task_type = router.classify_task("你好，今天天气怎么样？", has_image=False)
        assert task_type == TaskType.TEXT_SIMPLE.value

    def test_classify_medical(self, router):
        """医学问题分类"""
        task_type = router.classify_task(
            "患者有高血压，应该如何用药？",
            has_image=False
        )
        assert task_type == TaskType.MEDICAL.value

    def test_classify_code(self, router):
        """代码任务分类"""
        task_type = router.classify_task(
            "用 Python 写一个快速排序",
            has_image=False
        )
        assert task_type == TaskType.CODE.value

    def test_classify_complex_reasoning(self, router):
        """复杂推理分类"""
        task_type = router.classify_task(
            "分析一下这个算法的优缺点，并提出改进建议",
            has_image=False
        )
        assert task_type == TaskType.TEXT_COMPLEX.value

    def test_classify_vision(self, router):
        """视觉任务分类"""
        task_type = router.classify_task("描述这张图片", has_image=True)
        assert task_type == TaskType.VISION_ANALYSIS.value

    def test_assess_complexity(self, router):
        """复杂度评估"""
        # 短简单任务
        complexity = router.assess_complexity("你好", TaskType.TEXT_SIMPLE.value)
        assert complexity == Complexity.SIMPLE.value

        # 长任务或复杂关键词
        long_task = " ".join(["分析"] * 100)
        complexity = router.assess_complexity(long_task, TaskType.TEXT_COMPLEX.value)
        assert complexity in [Complexity.MEDIUM.value, Complexity.COMPLEX.value, Complexity.CRITICAL.value]


class TestSelectProvider:
    """Provider 选择测试"""

    def test_simple_task_uses_minimax(self, router):
        """简单任务使用 MiniMax"""
        provider = router.select_provider(TaskType.TEXT_SIMPLE.value, Complexity.SIMPLE.value)
        assert provider == "minimax"

    def test_vision_medium_uses_local(self, router):
        """视觉任务（中等复杂度）使用本地快速模型"""
        provider = router.select_provider(
            TaskType.VISION_ANALYSIS.value,
            Complexity.MEDIUM.value
        )
        assert provider == "local"  # MEDIUM 用 local 快速兜底

    def test_vision_critical_uses_openrouter(self, router):
        """视觉任务（高复杂度）使用 OpenRouter 精分析"""
        provider = router.select_provider(
            TaskType.VISION_ANALYSIS.value,
            Complexity.CRITICAL.value
        )
        assert provider == "openrouter"

    def test_medical_uses_minimax(self, router):
        """医学问题使用 MiniMax"""
        provider = router.select_provider(TaskType.MEDICAL.value, Complexity.MEDIUM.value)
        assert provider == "minimax"

    def test_complex_code_uses_deepseek(self, router):
        """复杂代码任务使用 DeepSeek"""
        provider = router.select_provider(
            TaskType.CODE.value,
            Complexity.COMPLEX.value
        )
        assert provider == "deepseek"

    def test_complex_reasoning_uses_openrouter(self, router):
        """复杂推理使用 OpenRouter"""
        provider = router.select_provider(
            TaskType.TEXT_COMPLEX.value,
            Complexity.COMPLEX.value
        )
        assert provider == "openrouter"


class TestCostEstimate:
    """成本估算测试"""

    def test_simple_task_low_cost(self, router):
        """简单任务低成本"""
        estimate = router.cost_estimate(TaskType.TEXT_SIMPLE.value, Complexity.SIMPLE.value)
        assert estimate["tier"] == "low"

    def test_vision_task_medium_cost(self, router):
        """视觉任务中等成本"""
        estimate = router.cost_estimate(
            TaskType.VISION_ANALYSIS.value,
            Complexity.MEDIUM.value
        )
        assert estimate["tier"] in ["medium", "high"]


class TestShouldUpgrade:
    """是否升级测试"""

    def test_simple_no_upgrade(self, router):
        """简单任务不需要升级"""
        assert router.should_upgrade(TaskType.TEXT_SIMPLE.value, Complexity.SIMPLE.value) is False

    def test_complex_needs_upgrade(self, router):
        """复杂任务可能需要升级"""
        # 这取决于 upgrade_threshold 配置
        result = router.should_upgrade(TaskType.TEXT_COMPLEX.value, Complexity.CRITICAL.value)
        assert isinstance(result, bool)
