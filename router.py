#!/usr/bin/env python3
"""
Artemis 任务路由系统
根据任务类型、复杂度、成本等因素选择最优 Provider
"""

import re
from typing import Dict, Any, Optional, List
from enum import Enum


class TaskType(Enum):
    """任务类型枚举"""
    TEXT_SIMPLE = "text_simple"        # 简单文字
    TEXT_COMPLEX = "text_complex"     # 复杂文字/推理
    MEDICAL = "medical"                # 医学专业问题
    VISION_ANALYSIS = "vision"         # 视觉分析
    CODE = "code"                      # 代码相关
    CREATIVE = "creative"              # 创意任务
    UNKNOWN = "unknown"


class Complexity(Enum):
    """复杂度等级"""
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    CRITICAL = "critical"


class TaskRouter:
    """
    任务路由类
    决定每个任务使用哪个 Provider 和模型
    """
    
    # Provider 配置（与 llm.py 保持一致）
    PROVIDERS = {
        "minimax": {
            "models": ["abab6.5s-chat", "abab6.5-chat", "gemma-7b"],
            "strengths": ["中文", "快速", "成本低"],
            "cost_tier": 1,
            "supports_vision": False,
        },
        "openrouter": {
            "models": ["openai/gpt-4o-mini", "openai/gpt-4o", "anthropic/claude-3-haiku",
                       "deepseek/deepseek-chat-v3-0324", "google/gemini-2.0-flash"],
            "strengths": ["通用", "视觉", "复杂推理"],
            "cost_tier": 2,
            "supports_vision": True,
        },
        "deepseek": {
            "models": ["deepseek-chat", "deepseek-coder"],
            "strengths": ["编程", "推理", "成本低"],
            "cost_tier": 1,
            "supports_vision": False,
        },
        "anthropic": {
            "models": ["claude-3-5-haiku-20241107", "claude-3-opus-4-5-20241120",
                       "claude-3-sonnet-4-20250514"],
            "strengths": ["复杂推理", "视觉", "精确"],
            "cost_tier": 3,
            "supports_vision": True,
        },
        "google": {
            "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
            "strengths": ["多模态", "快速", "免费额度"],
            "cost_tier": 1,
            "supports_vision": True,
        },
        "local": {
            "models": ["llama3.2-vision", "qwen2.5"],
            "strengths": ["本地", "快速", "隐私"],
            "cost_tier": 1,
            "supports_vision": True,
        }
    }
    
    # 医学关键词
    MEDICAL_KEYWORDS = [
        "医学", "医疗", "医生", "医院", "诊断", "治疗", "药物", "药品",
        "症状", "病因", "检查", "检验", "影像", "CT", "MRI", "X光",
        "血压", "血糖", "心率", "体温", "血常规", "尿常规",
        "内科", "外科", "儿科", "妇科", "骨科", "神经科",
        "糖尿病", "高血压", "心脏病", "癌症", "肿瘤",
        "处方", "非处方", "服药", "手术", "住院"
    ]
    
    # 复杂推理关键词
    COMPLEX_KEYWORDS = [
        "分析", "推理", "比较", "评估", "预测", "计算",
        "证明", "推导", "归纳", "演绎", "综合",
        "策略", "方案", "计划", "优化", "设计"
    ]
    
    # 代码关键词
    CODE_KEYWORDS = [
        "代码", "程序", "函数", "变量", "API", "开发",
        "调试", "测试", "部署", "Git", "数据库",
        "Python", "JavaScript", "Java", "C++", "Go"
    ]
    
    # 视觉相关
    VISION_KEYWORDS = [
        "图片", "图像", "截图", "照片", "画面",
        "图表", "图示", "视觉", "识别", "检测"
    ]
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化路由系统
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.text_default = config.get("routing", {}).get("text_default", "minimax")
        self.vision_primary = config.get("routing", {}).get("vision_primary", "openrouter")
        self.vision_fallback = config.get("routing", {}).get("vision_fallback", "local")
        self.upgrade_threshold = config.get("routing", {}).get("upgrade_threshold", "medium")
    
    def classify_task(self, task_text: str, has_image: bool = False) -> str:
        """
        判断任务类型
        
        Args:
            task_text: 任务文本
            has_image: 是否包含图片
            
        Returns:
            任务类型字符串
        """
        if has_image:
            return TaskType.VISION_ANALYSIS.value
        
        text_lower = task_text.lower()
        
        # 检查医学关键词
        if any(kw in task_text for kw in self.MEDICAL_KEYWORDS):
            return TaskType.MEDICAL.value
        
        # 检查代码关键词（case-insensitive）
        if any(kw.lower() in text_lower for kw in self.CODE_KEYWORDS):
            return TaskType.CODE.value
        
        # 检查复杂推理
        if any(kw in task_text for kw in self.COMPLEX_KEYWORDS):
            return TaskType.TEXT_COMPLEX.value
        
        # 检查视觉相关（无图片但有视觉描述）
        if any(kw in text_lower for kw in self.VISION_KEYWORDS):
            return TaskType.VISION_ANALYSIS.value
        
        # 默认简单文字
        return TaskType.TEXT_SIMPLE.value
    
    def assess_complexity(self, task_text: str, task_type: str) -> str:
        """
        评估任务复杂度
        
        Args:
            task_text: 任务文本
            task_type: 任务类型
            
        Returns:
            复杂度等级
        """
        # 视觉任务默认中等以上
        if task_type == TaskType.VISION_ANALYSIS.value:
            if any(word in task_text.lower() for word in ["分析", "详细", "精确"]):
                return Complexity.COMPLEX.value
            return Complexity.MEDIUM.value
        
        # 医学问题默认复杂
        if task_type == TaskType.MEDICAL.value:
            if any(word in task_text for word in ["诊断", "鉴别", "治疗方案"]):
                return Complexity.CRITICAL.value
            return Complexity.COMPLEX.value
        
        # 代码任务
        if task_type == TaskType.CODE.value:
            if any(word in task_text.lower() for word in ["架构", "系统设计", "优化"]):
                return Complexity.COMPLEX.value
            return Complexity.MEDIUM.value
        
        # 文字任务复杂度评估
        length = len(task_text)
        
        # 长度指标
        if length < 50:
            return Complexity.SIMPLE.value
        elif length < 200:
            return Complexity.MEDIUM.value
        else:
            # 额外检查复杂度关键词
            if any(kw in task_text for kw in self.COMPLEX_KEYWORDS):
                return Complexity.COMPLEX.value
            return Complexity.MEDIUM.value
    
    def select_provider(self, task_type: str, complexity: str) -> str:
        """
        选择最优 Provider
        
        核心逻辑：
        - 简单文字 → MiniMax
        - 医学专业问题 → MiniMax + 触发医学 skill
        - 截图/图片 → OpenRouter gpt-4o-mini（精分析）或本地 ollama（快兜底）
        - 复杂推理 → OpenRouter claude
        - 极度复杂 → OpenRouter gpt-4o
        
        Args:
            task_type: 任务类型
            complexity: 复杂度
            
        Returns:
            Provider 名称
        """
        # 视觉任务
        if task_type == TaskType.VISION_ANALYSIS.value:
            if complexity in [Complexity.SIMPLE.value, Complexity.MEDIUM.value]:
                return self.vision_fallback  # 本地快速兜底
            return self.vision_primary  # OpenRouter 精分析
        
        # 简单文字任务
        if task_type == TaskType.TEXT_SIMPLE.value and complexity == Complexity.SIMPLE.value:
            return self.text_default  # MiniMax
        
        # 复杂推理
        if task_type == TaskType.TEXT_COMPLEX.value:
            if complexity == Complexity.CRITICAL.value:
                return "openrouter"  # 模型由 llm.py 的 DEFAULT_MODELS 决定
            return "openrouter"  # claude-3-haiku from openrouter
        
        # 医学问题 - 复杂但用 MiniMax + skill
        if task_type == TaskType.MEDICAL.value:
            return self.text_default  # MiniMax
        
        # 代码任务
        if task_type == TaskType.CODE.value:
            if complexity in [Complexity.SIMPLE.value, Complexity.MEDIUM.value]:
                return self.text_default
            return "deepseek"  # deepseek-coder is good for complex code
        
        # 默认
        return self.text_default
    
    def cost_estimate(self, task_type: str, complexity: str) -> Dict[str, Any]:
        """
        估算任务成本
        
        Args:
            task_type: 任务类型
            complexity: 复杂度
            
        Returns:
            成本估算字典
        """
        # 基础成本等级 (1-10)
        base_costs = {
            TaskType.TEXT_SIMPLE.value: 1,
            TaskType.TEXT_COMPLEX.value: 3,
            TaskType.MEDICAL.value: 2,
            TaskType.VISION_ANALYSIS.value: 4,
            TaskType.CODE.value: 2,
            TaskType.CREATIVE.value: 3,
            TaskType.UNKNOWN.value: 2
        }
        
        complexity_multipliers = {
            Complexity.SIMPLE.value: 1.0,
            Complexity.MEDIUM.value: 1.5,
            Complexity.COMPLEX.value: 2.5,
            Complexity.CRITICAL.value: 4.0
        }
        
        base = base_costs.get(task_type, 2)
        multiplier = complexity_multipliers.get(complexity, 1.5)
        
        estimated = base * multiplier
        
        return {
            "relative_cost": round(estimated, 1),
            "tier": "low" if estimated < 2 else "medium" if estimated < 4 else "high",
            "recommendation": "优先 MiniMax" if estimated < 3 else "可考虑升级"
        }
    
    def should_upgrade(self, task_type: str, complexity: str) -> bool:
        """
        判断当前结果是否需要升级处理
        
        Args:
            task_type: 任务类型
            complexity: 复杂度
            
        Returns:
            是否需要升级
        """
        threshold = self.upgrade_threshold
        
        threshold_levels = {
            "simple": [Complexity.SIMPLE.value],
            "medium": [Complexity.SIMPLE.value, Complexity.MEDIUM.value],
            "complex": [Complexity.SIMPLE.value, Complexity.MEDIUM.value, Complexity.COMPLEX.value],
            "critical": []  # 从不自动升级
        }
        
        allowed = threshold_levels.get(threshold, [Complexity.SIMPLE.value, Complexity.MEDIUM.value])
        
        return complexity not in allowed
    
    def get_recommended_skill(self, task_type: str, task_text: str) -> Optional[str]:
        """
        获取推荐技能（如果有的话）
        
        Args:
            task_type: 任务类型
            task_text: 任务文本
            
        Returns:
            技能名称或 None
        """
        if task_type == TaskType.MEDICAL.value:
            return "medical-guidelines"
        
        return None
    
    def explain_routing(self, task_text: str, has_image: bool = False) -> str:
        """
        生成路由决策解释（用于调试）
        
        Args:
            task_text: 任务文本
            has_image: 是否包含图片
            
        Returns:
            决策解释字符串
        """
        task_type = self.classify_task(task_text, has_image)
        complexity = self.assess_complexity(task_text, task_type)
        provider = self.select_provider(task_type, complexity)
        cost = self.cost_estimate(task_type, complexity)
        
        lines = [
            f"任务类型: {task_type}",
            f"复杂度: {complexity}",
            f"推荐 Provider: {provider}",
            f"预估成本等级: {cost['tier']} ({cost['relative_cost']})",
            f"升级建议: {cost['recommendation']}"
        ]
        
        skill = self.get_recommended_skill(task_type, task_text)
        if skill:
            lines.append(f"推荐技能: {skill}")
        
        return "\n".join(lines)


# ==================== 单元测试 ====================

if __name__ == "__main__":
    print("[TaskRouter] 运行单元测试...\n")
    
    # 模拟配置
    config = {
        "routing": {
            "text_default": "minimax",
            "vision_primary": "openrouter",
            "vision_fallback": "local",
            "upgrade_threshold": "medium"
        }
    }
    
    router = TaskRouter(config)
    
    test_cases = [
        ("你好，今天天气怎么样？", False),
        ("帮我写一段 Python 代码实现快速排序", False),
        ("这个 CT 影像有什么问题？", True),
        ("高血压患者应该如何选择降压药？", False),
        ("分析一下这个图表的数据趋势", True),
        ("请比较一下机器学习和深度学习的区别", False),
    ]
    
    for text, has_image in test_cases:
        print(f"输入: {text[:30]}... [图片: {has_image}]")
        print(router.explain_routing(text, has_image))
        print("-" * 40)
    
    print("\n[TaskRouter] ✓ 测试完成!")
