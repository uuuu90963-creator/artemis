#!/usr/bin/env python3
"""
Artemis Agent - 核心入口
轻量高效的 AI 助手，以感知优先、好奇进化、温暖专业为核心特质

路径系统：使用 paths.py，兼容 OpenClaw 工作区和 Hermes 双生态
配置系统：使用 config.py 的 schema versioning 设计
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union

# 路径兼容层（必须在其他导入之前设置）
import paths as _paths
_paths.setup_python_path()

# 基础路径（来自 paths 系统）
BASE_DIR = _paths.get_artemis_home()

# 配置系统
import config as _config

# 导入子模块（延迟导入，避免循环依赖）
from memory import MemoryStore
from router import TaskRouter
from evolution_engine import EvolutionEngine
from llm import LLMClient
from cron import CronScheduler
from plugins.mcp_plugin import MCPPluginManager
from agent import ArtemisAgent, CostTracker
from vision import VisionEngine


# ═══════════════════════════════════════════════════════════
#  Skill Bridge（OpenClaw 工作区技能发现）
# ═══════════════════════════════════════════════════════════

def _build_skill_context(task_text: str) -> str:
    """
    根据任务文本自动发现并注入相关 skill 内容到 prompt。
    支持 Artemis 本地 skills 和 OpenClaw 工作区 skills。
    """
    from skills.skill_manager import SkillManager

    context_parts = []
    artemis_skills_dir = BASE_DIR / "skills"
    openclaw_workspace = _paths.get_openclaw_workspace()

    # 遍历所有 skill 目录
    for skills_dir in [artemis_skills_dir] + (
        [(openclaw_workspace / "skills")] if openclaw_workspace else []
    ):
        if not skills_dir.exists():
            continue

        sm = SkillManager(skills_dir)
        suggestions = sm.suggest_skills_for_task(task_text)

        for skill in suggestions[:3]:  # 最多注入 3 个相关 skill
            skill_md_path = skills_dir / skill.name / "SKILL.md"
            if skill_md_path.exists():
                try:
                    skill_content = skill_md_path.read_text(encoding="utf-8")
                    # 截取前 1500 字符（避免 prompt 过长）
                    truncated = skill_content[:1500]
                    context_parts.append(
                        f"\n\n[ Skill: {skill.name} ]\n{truncated}\n[ Skill End: {skill.name} ]\n"
                    )
                except Exception:
                    pass

    if context_parts:
        return "\n".join(context_parts) + "\n"
    return ""


# ═══════════════════════════════════════════════════════════
#  Artemis 主类
# ═══════════════════════════════════════════════════════════

class Artemis:
    """
    Artemis Agent 主入口类

    支持延迟初始化（auto-init）：实例化后首次调用 run_task/chat 等方法时自动初始化。
    也支持手动调用 initialize() 先初始化。
    """

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.soul: Optional[Dict[str, Any]] = None
        self.config: Optional[Dict[str, Any]] = None
        self.memory: Optional[MemoryStore] = None
        self.router: Optional[TaskRouter] = None
        self.evolution: Optional[EvolutionEngine] = None
        self.llm: Optional[LLMClient] = None
        self.cron: Optional[CronScheduler] = None
        self.plugins: Optional[MCPPluginManager] = None
        self.agent: Optional[ArtemisAgent] = None
        self.cost_tracker: Optional[CostTracker] = None
        self.vision: Optional[VisionEngine] = None
        self.task_count = 0
        self.current_provider = "auto"
        self._initialized = False

    # ==================== 初始化 ====================

    def ensure_initialized(self):
        """延迟初始化（如果尚未初始化，则初始化）"""
        if not self._initialized:
            self.initialize()

    def initialize(self):
        """初始化所有子系统"""
        if self._initialized:
            return

        print("\n[Artemis] 初始化中...")

        # 加载灵魂
        self._load_soul()

        # 加载配置（使用 config.py 的 schema versioning 系统）
        self._load_config()

        # 初始化记忆系统
        self._init_memory()

        # 初始化路由系统
        self.router = TaskRouter(self.config)
        print("[Artemis] ✓ 路由系统就绪")

        # 初始化多模型 LLM 客户端
        self.llm = LLMClient(self.config)
        available = self.llm.get_available_providers()
        print(f"[Artemis] ✓ LLM 客户端就绪 (可用: {', '.join(available) if available else '无'})")

        # 初始化进化引擎
        self._init_evolution(available)

        # 初始化定时任务调度器
        self._init_cron()

        # 初始化 MCP 插件管理器
        plugins_dir = BASE_DIR / "plugins"
        self.plugins = MCPPluginManager(plugins_dir)
        all_tools = self.plugins.get_all_tools()
        print(f"[Artemis] ✓ MCP 插件系统就绪 ({len(all_tools)} 个工具)")

        # 初始化 Agent Loop
        self.agent = ArtemisAgent(self.llm, self.plugins)
        print(f"[Artemis] ✓ Agent Loop 就绪")

        # 初始化成本追踪
        self.cost_tracker = CostTracker()
        print(f"[Artemis] ✓ 成本追踪就绪")

        # 初始化双通道视觉引擎
        self._init_vision()

        self._initialized = True
        print("[Artemis] ✓ 初始化完成！\n")

    # ==================== 子系统初始化 ====================

    def _load_soul(self):
        """加载人格设定"""
        soul_path = BASE_DIR / "SOUL.md"
        if soul_path.exists():
            with open(soul_path, "r", encoding="utf-8") as f:
                raw = f.read()
            self.soul = {"raw": raw}
            print(f"[Artemis] ✓ 灵魂设定已加载 ({len(raw)} 字符)")
        else:
            self.soul = {"raw": "我是 Artemis，一个温暖的 AI 助手。"}
            print("[Artemis] ⚠ 未找到 SOUL.md，使用默认设定")

    def _load_config(self):
        """加载配置文件（使用 config.py）"""
        # 优先用 paths 系统获取配置路径
        cfg_path = self.config_path or _paths.get_config_path()
        if cfg_path.exists():
            # 让 config.py 处理加载和迁移
            self.config = _config.load_config()
            ver = self.config.get("_schema_version", "?")
            print(f"[Artemis] ✓ 配置已加载 (schema: v{ver})")
        else:
            # 使用 config.py 的默认配置
            self.config = _config.load_config()
            print("[Artemis] ⚠ 未找到 config.yaml，使用默认配置")

    def _init_memory(self):
        """初始化记忆系统"""
        mem_cfg = self.config.get("memory", {})
        db_path_str = mem_cfg.get("db_path", "memories/memory.db")
        db_path = BASE_DIR / db_path_str
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.memory = MemoryStore(db_path)
            print(f"[Artemis] ✓ 记忆系统就绪 ({self.memory.count()} 条记忆)")
        except Exception as e:
            logging.warning("记忆系统初始化失败: %s，使用 fallback", e)
            self.memory = MemoryStore(_paths.get_memories_dir() / "memory_fallback.db")

    def _init_evolution(self, available: list):
        """初始化进化引擎"""
        evo_cfg = self.config.get("evolution", {})
        log_dir = _paths.get_logs_dir() / "evolution"
        log_dir.mkdir(parents=True, exist_ok=True)
        evo_provider = "openrouter" if "openrouter" in available else ("minimax" if "minimax" in available else "minimax")
        self.evolution = EvolutionEngine(
            log_dir=log_dir,
            反思_after_tasks=evo_cfg.get("反思_after_tasks", 3),
            llm_client=self.llm,
            provider=evo_provider,
        )
        print(f"[Artemis] ✓ 进化系统就绪 (LLM反思: {evo_provider})")

    def _init_cron(self):
        """初始化 Cron 调度器"""
        try:
            cron_db = _paths.get_memories_dir() / "cron.db"
            self.cron = CronScheduler(agent=self, db_path=cron_db)
            jobs = self.cron.list_jobs()
            print(f"[Artemis] ✓ Cron 调度器就绪 ({len(jobs)} 个任务)")
        except Exception as e:
            logging.warning("Cron 调度器初始化失败: %s", e)
            self.cron = None

    def _init_vision(self):
        """初始化视觉引擎"""
        try:
            self.vision = VisionEngine()
            print("[Artemis] ✓ 视觉引擎就绪 (通道: local+cloud)")
        except Exception as e:
            logging.warning("视觉引擎初始化失败: %s", e)
            self.vision = None

    # ==================== 核心执行 ====================

    def route_task(self, task: Union[Dict[str, Any], str]) -> Dict[str, Any]:
        """
        路由决策 - 判断任务类型并选择最优处理方式

        Args:
            task: 任务字典或字符串（字符串会自动转为字典）
        Returns:
            路由决策结果
        """
        self.ensure_initialized()

        # 支持字符串输入
        if isinstance(task, str):
            task = {"content": task}

        task_text = task.get("content", "") or ""
        has_image = "image" in task or "image_url" in task

        task_type = self.router.classify_task(task_text, has_image)
        complexity = self.router.assess_complexity(task_text, task_type)
        provider = self.router.select_provider(task_type, complexity)
        cost = self.router.cost_estimate(task_type, complexity)
        upgrade_needed = self.router.should_upgrade(task_type, complexity)

        return {
            "task_type": task_type,
            "complexity": complexity,
            "provider": provider,
            "estimated_cost": cost,
            "upgrade_needed": upgrade_needed,
            "has_image": has_image,
        }

    def run_task(self, task: Union[Dict[str, Any], str]) -> Dict[str, Any]:
        """
        执行任务（使用 Agent Loop，支持工具调用）

        Args:
            task: 任务字典或字符串
        Returns:
            执行结果
        """
        self.ensure_initialized()

        # 支持字符串输入
        if isinstance(task, str):
            task = {"content": task}

        self.task_count += 1

        # 路由决策
        route = self.route_task(task)
        task_text = task.get("content", "") or ""

        print(f"[Artemis] 任务 #{self.task_count} | 类型: {route['task_type']} | "
              f"复杂度: {route['complexity']} | Provider: {route['provider']}")

        # 图片预处理
        vision_context = self._process_image(task, route, task_text)

        # 构建 system prompt
        system_parts = []
        if self.soul:
            system_parts.append(self.soul["raw"])
        if self.memory:
            profile = self.memory.get_user_profile()
            if profile.get("name"):
                system_parts.append(f"[用户信息] 姓名: {profile['name']}")
            if profile.get("preferences"):
                system_parts.append(f"偏好: {profile['preferences']}")

        # 自动注入相关 skill
        skill_context = _build_skill_context(task_text)
        if skill_context:
            system_parts.append(f"\n[相关技能]\n{skill_context}")

        system_prompt = "\n\n".join(system_parts)

        # 用户内容（vision context 优先）
        user_content = vision_context + task_text

        # 执行
        try:
            agent_result = self.agent.chat(
                prompt=user_content,
                system_prompt=system_prompt,
                image=None,
                session_id=f"task_{self.task_count}",
            )

            if agent_result.get("success"):
                result = {
                    "success": True,
                    "content": agent_result.get("content", ""),
                    "provider_used": agent_result.get("provider", route["provider"]),
                    "model_used": agent_result.get("model", ""),
                    "usage": agent_result.get("usage", {}),
                    "tool_calls": agent_result.get("tool_calls", []),
                    "total_turns": agent_result.get("total_turns", 1),
                    "cost_usd": agent_result.get("cost_usd", 0),
                    "route": route,
                    "matched_skills": agent_result.get("matched_skills", []),
                }
            else:
                result = {
                    "success": False,
                    "content": f"LLM 调用失败: {agent_result.get('content', '未知错误')}",
                    "provider_used": route["provider"],
                    "route": route,
                }
        except Exception as e:
            result = {
                "success": False,
                "content": f"执行出错: {str(e)}",
                "provider_used": route["provider"],
                "route": route,
            }

        # 记录记忆
        if task_text and self.memory:
            self.memory.add_memory(
                content=f"用户任务: {task_text[:200]}",
                tags=["task", route["task_type"]],
                source="task",
            )

        # 记录进化
        if self.evolution:
            self.evolution.log_task(
                task=task_text,
                result=result.get("content", ""),
                success=result.get("success", False),
                task_type=route["task_type"],
                complexity=route["complexity"],
            )

            if self.evolution.should_reflect(self.task_count):
                insights = self.evolve()
                result["insights"] = insights

        return result

    def _process_image(self, task: Dict, route: Dict, task_text: str) -> str:
        """图片预处理，返回 vision context 字符串"""
        image_path = task.get("image") or task.get("image_url")
        if not image_path or not self.vision:
            return ""

        print("[Artemis] 检测到图片，预处理中...")
        try:
            medical_kw = ["ct", "mri", "x光", "x线", "超声", "影像", "片子", "诊断"]
            complexity = "complex" if any(k in task_text.lower() for k in medical_kw) else "medium"
            vis = self.vision.analyze(image_path, task_text or "这张图里有什么？", complexity=complexity)
            if vis.get("success"):
                route["task_type"] = "vision"
                route["provider"] = "openrouter"
                print(f"[Artemis] ✓ 视觉分析完成 (通道: {vis.get('selected_channel', 'cloud')})")
                return f"\n[视觉分析结果]\n{vis['content']}\n[视觉分析结束]\n\n"
            else:
                print(f"[Artemis] ! 视觉分析失败: {vis.get('error', '未知')}")
        except Exception as e:
            print(f"[Artemis] ! 视觉分析异常: {e}")
        return ""

    def evolve(self) -> Dict[str, Any]:
        """自我反思和进化"""
        self.ensure_initialized()
        if not self.evolution:
            return {"summary": "进化引擎未就绪"}

        print("\n[Artemis] 🔄 触发自我反思...")

        reflection = self.evolution.reflect()
        gaps = self.evolution.detect_skill_gaps()
        insights = self.evolution.generate_insights(gaps)

        if self.memory:
            self.memory.add_memory(
                content=f"反思: {insights.get('summary', '完成了反思')}",
                tags=["reflection", "evolution"],
                source="evolution",
            )

        print(f"[Artemis] ✓ 反思完成: {insights.get('summary', '')}")
        return insights

    # ==================== 交互接口 ====================

    def chat(self, message: str, image: Optional[str] = None) -> str:
        """对话接口"""
        self.ensure_initialized()
        task = {"content": message}
        if image:
            task["image"] = image
        result = self.run_task(task)
        return result.get("content", "处理中...")

    def remember(self, query: str, top_k: int = 5) -> list:
        """搜索记忆"""
        self.ensure_initialized()
        return self.memory.search_memories(query, top_k) if self.memory else []

    def get_user_profile(self) -> Dict[str, Any]:
        """获取用户画像"""
        self.ensure_initialized()
        return self.memory.get_user_profile() if self.memory else {}

    def set_provider(self, provider: str) -> bool:
        """切换 LLM provider"""
        self.ensure_initialized()
        if provider == "auto":
            self.current_provider = "auto"
            print("[Artemis] 已切换为 auto 模式（自动选择）")
            return True
        if self.llm and self.llm.is_provider_available(provider):
            self.current_provider = provider
            print(f"[Artemis] 已切换为 {provider}")
            return True
        available = self.llm.get_available_providers() if self.llm else []
        print(f"[Artemis] {provider} 不可用，可用: {available}")
        return False

    # ==================== 技能系统 ====================

    def list_skills(self) -> list:
        """列出可用技能（来自所有 skill 目录）"""
        self.ensure_initialized()
        all_skills = []
        for skills_dir in _paths.get_skills_dirs():
            if not skills_dir.exists():
                continue
            for item in skills_dir.iterdir():
                if item.is_dir() and (item / "SKILL.md").exists():
                    all_skills.append(item.name)
        return all_skills

    def load_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """加载技能内容"""
        self.ensure_initialized()
        for skills_dir in _paths.get_skills_dirs():
            skill_path = skills_dir / skill_name / "SKILL.md"
            if skill_path.exists():
                with open(skill_path, "r", encoding="utf-8") as f:
                    return {"name": skill_name, "content": f.read()}
        return None

    # ==================== 工作空间 ====================

    def read_agents_md(self) -> str:
        """读取 AGENTS.md"""
        self.ensure_initialized()
        agents_path = _paths.get_workspace_dir() / "AGENTS.md"
        if agents_path.exists():
            return agents_path.read_text(encoding="utf-8")
        return ""


# ═══════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════

def create_instance() -> Artemis:
    """创建已初始化的 Artemis 实例"""
    agent = Artemis()
    agent.initialize()
    return agent


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Artemis AI Agent")
    parser.add_argument("--tui", action="store_true", help="启动 TUI 界面")
    parser.add_argument("--cli", action="store_true", help="启动 CLI 交互模式")
    parser.add_argument("--daemon", action="store_true", help="后台运行（仅启动 Cron 调度器）")
    args = parser.parse_args()

    print("=" * 50)
    print(" Artemis Agent v0.1.0 ")
    print(" 感知优先 · 好奇进化 · 温暖专业 ")
    print("=" * 50)

    agent = create_instance()

    if args.daemon:
        print("\n[Artemis] 启动 Cron 调度器（后台）...")
        if agent.cron:
            agent.cron.start()
            print(f"[Artemis] ✓ Cron 调度器已启动 ({len(agent.cron.list_jobs())} 个任务)")
            print("[Artemis] 后台运行中，按 Ctrl+C 停止")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n[Artemis] 停止 Cron 调度器...")
                agent.cron.stop()
                print("[Artemis] 已停止")
        else:
            print("[Artemis] Cron 调度器不可用")

    elif args.tui:
        from tui import TUIBootstrap
        print("\n[Artemis] 启动 TUI 界面...")
        tui = TUIBootstrap(agent)
        tui.run()
    else:
        # 默认 CLI 交互模式
        from artemis_cli import cmd_chat
        cmd_chat(argparse.Namespace())
