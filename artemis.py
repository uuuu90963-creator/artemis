#!/usr/bin/env python3
"""
Artemis Agent - 核心入口
轻量高效的 AI 助手，以感知优先、好奇进化、温暖专业为核心特质
"""

import os
import sys
import json
import time
import yaml
from pathlib import Path
from typing import Dict, Any, Optional

# 基础路径
BASE_DIR = Path.home() / ".hermes" / "artemis"
BASE_DIR.mkdir(parents=True, exist_ok=True)

# 导入子模块
from memory import MemoryStore
from router import TaskRouter
from evolution_engine import EvolutionEngine
from llm import LLMClient
from cron import CronScheduler
from plugins.mcp_plugin import MCPPluginManager
from agent import ArtemisAgent, CostTracker
from vision import VisionEngine


class Artemis:
    """Artemis Agent 主入口类"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (BASE_DIR / "config.yaml")
        self.soul = None
        self.config = None
        self.memory = None
        self.router = None
        self.evolution = None
        self.llm = None  # 多模型 LLM 客户端
        self.cron = None  # 定时任务调度器
        self.plugins = None  # MCP 插件管理器
        self.agent = None  # Agent Loop（支持工具调用）
        self.cost_tracker = None  # 成本追踪
        self.vision = None  # 双通道视觉引擎
        self.task_count = 0
        self.current_provider = "auto"  # 当前使用的 provider
        
    # ==================== 核心方法 ====================
    
    def load_soul(self) -> Dict[str, Any]:
        """加载人格设定"""
        soul_path = BASE_DIR / "SOUL.md"
        if soul_path.exists():
            with open(soul_path, "r", encoding="utf-8") as f:
                self.soul = {"raw": f.read()}
            print(f"[Artemis] ✓ 灵魂设定已加载 ({len(self.soul['raw'])} 字符)")
        else:
            self.soul = {"raw": "我是 Artemis，一个温暖的 AI 助手。"}
            print("[Artemis] ⚠ 未找到 SOUL.md，使用默认设定")
        return self.soul
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            print(f"[Artemis] ✓ 配置已加载 (版本: {self.config.get('version', 'unknown')})")
        else:
            # 默认配置
            self.config = {
                "name": "artemis",
                "version": "0.1.0",
                "routing": {
                    "text_default": "minimax",
                    "vision_primary": "openrouter",
                    "vision_fallback": "local",
                    "upgrade_threshold": "medium"
                },
                "memory": {
                    "type": "sqlite",
                    "path": "memories/memory.db",
                    "embedding_model": "text-embedding-3-small",
                    "max_entries": 10000
                },
                "skills": {
                    "directory": "skills",
                    "marketplace": "https://artemis-skills.market"
                },
                "evolution": {
                    "enabled": True,
                    "反思_after_tasks": 3,          # 每N个任务后反思一次
                    "log_dir": "logs/evolution"      # 相对 BASE_DIR
                },
                "workspace": {
                    "path": "workspace",
                    "agents_md": "AGENTS.md"
                }
            }
            print("[Artemis] ⚠ 未找到 config.yaml，使用默认配置")
        return self.config
    
    def initialize(self):
        """初始化所有子系统"""
        print("\n[Artemis] 初始化中...")
        
        # 加载灵魂和配置
        self.load_soul()
        self.load_config()
        
        # 初始化记忆系统
        db_path = BASE_DIR / self.config["memory"]["path"]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.memory = MemoryStore(db_path)
            print(f"[Artemis] ✓ 记忆系统就绪 ({self.memory.count()} 条记忆)")
        except Exception as e:
            print(f"[Artemis] ⚠ 记忆系统初始化失败: {e}")
            # Create in-memory fallback
            from memory import MemoryStore
            self.memory = MemoryStore(Path("/tmp/artemis_memory_fallback.db"))
        
        # 初始化路由系统
        self.router = TaskRouter(self.config)
        print("[Artemis] ✓ 路由系统就绪")
        
        # 初始化多模型 LLM 客户端
        self.llm = LLMClient(self.config)
        available = self.llm.get_available_providers()
        print(f"[Artemis] ✓ LLM 客户端就绪 (可用: {', '.join(available) if available else '无'})")
        
        # 初始化进化引擎（使用 LLM 进行真实反思）
        log_dir = BASE_DIR / self.config["evolution"]["log_dir"]
        log_dir.mkdir(parents=True, exist_ok=True)
        # 优先用 openrouter 做反思（更精准），降级用 minimax
        evo_provider = "openrouter" if "openrouter" in available else ("minimax" if "minimax" in available else "minimax")
        self.evolution = EvolutionEngine(
            log_dir=log_dir,
            反思_after_tasks=self.config["evolution"]["反思_after_tasks"],
            llm_client=self.llm,
            provider=evo_provider,
        )
        print(f"[Artemis] ✓ 进化系统就绪 (LLM反思: {evo_provider})")
        
        # 初始化定时任务调度器
        cron_db = BASE_DIR / "memories" / "cron.db"
        try:
            self.cron = CronScheduler(agent=self, db_path=cron_db)
            jobs = self.cron.list_jobs()
            print(f"[Artemis] ✓ Cron 调度器就绪 ({len(jobs)} 个任务)")
        except Exception as e:
            print(f"[Artemis] ⚠ Cron 调度器初始化失败: {e}")
            self.cron = None
        
        # 初始化 MCP 插件管理器
        plugins_dir = BASE_DIR / "plugins"
        self.plugins = MCPPluginManager(plugins_dir)
        all_tools = self.plugins.get_all_tools()
        print(f"[Artemis] ✓ MCP 插件系统就绪 ({len(all_tools)} 个工具)")
        
        # 初始化 Agent Loop（支持工具调用）
        self.agent = ArtemisAgent(self.llm, self.plugins)
        print(f"[Artemis] ✓ Agent Loop 就绪")
        
        # 初始化成本追踪
        self.cost_tracker = CostTracker()
        print(f"[Artemis] ✓ 成本追踪就绪")
        
        # 初始化双通道视觉引擎
        try:
            self.vision = VisionEngine()
            print(f"[Artemis] ✓ 视觉引擎就绪 (通道: local+cloud)")
        except Exception as e:
            print(f"[Artemis] ! 视觉引擎初始化失败: {e}")
            self.vision = None
        
        print("[Artemis] 初始化完成！\n")
    
    def route_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        路由决策 - 判断任务类型并选择最优处理方式
        
        Args:
            task: 任务字典，包含 type, content, image 等
            
        Returns:
            路由决策结果，包含 provider, skill, complexity 等
        """
        task_text = task.get("content", "") or ""
        has_image = "image" in task or "image_url" in task
        
        # 分类任务
        task_type = self.router.classify_task(task_text, has_image)
        
        # 评估复杂度
        complexity = self.router.assess_complexity(task_text, task_type)
        
        # 选择 provider
        provider = self.router.select_provider(task_type, complexity)
        
        # 估算成本
        cost = self.router.cost_estimate(task_type, complexity)
        
        # 检查是否需要升级
        upgrade_needed = self.router.should_upgrade(task_type, complexity)
        
        return {
            "task_type": task_type,
            "complexity": complexity,
            "provider": provider,
            "estimated_cost": cost,
            "upgrade_needed": upgrade_needed,
            "has_image": has_image
        }
    
    def run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行任务（使用 Agent Loop，支持工具调用）
        
        Args:
            task: 任务字典
            
        Returns:
            执行结果
        """
        self.task_count += 1
        
        # 路由决策
        route = self.route_task(task)
        print(f"[Artemis] 任务 #{self.task_count} | 类型: {route['task_type']} | "
              f"复杂度: {route['complexity']} | Provider: {route['provider']}")
        
        # 处理图片：如果有图片，先用 Vision 引擎分析，把结果转成文字注入 prompt
        image_path = task.get("image") or task.get("image_url")
        vision_context = ""
        if image_path and self.vision:
            print(f"[Artemis] 检测到图片，预处理中...")
            try:
                # 自动判断复杂度
                medical_kw = ["ct", "mri", "x光", "x线", "超声", "影像", "片子", "诊断"]
                complexity = "complex" if any(k in task.get("content", "").lower() for k in medical_kw) else "medium"
                vis = self.vision.analyze(image_path, task.get("content", "这张图里有什么？"), complexity=complexity)
                if vis.get("success"):
                    vision_context = f"\n[视觉分析结果]\n{vis['content']}\n[视觉分析结束]\n\n"
                    route["task_type"] = "vision"
                    route["provider"] = "openrouter"
                    print(f"[Artemis] ✓ 视觉分析完成 (通道: {vis.get('selected_channel', 'cloud')})")
                else:
                    print(f"[Artemis] ! 视觉分析失败: {vis.get('error', '未知')}")
            except Exception as e:
                print(f"[Artemis] ! 视觉分析异常: {e}")
        
        # 构建 system prompt（注入 SOUL）
        system_prompt = self.soul["raw"] if self.soul else ""
        if self.memory:
            profile = self.memory.get_user_profile()
            if profile.get("name"):
                system_prompt += f"\n\n[用户信息] 姓名: {profile['name']}"
            if profile.get("preferences"):
                system_prompt += f"\n偏好: {profile['preferences']}"
        
        # 注入视觉分析结果到 prompt
        user_content = vision_context + task.get("content", "")
        
        try:
            # 使用 Agent Loop（支持工具调用）
            agent_result = self.agent.chat(
                prompt=user_content,
                system_prompt=system_prompt,
                image=None,  # 图片已在上面预处理成文字，不再传图片
                session_id=f"task_{self.task_count}",
            )
            
            if agent_result.get("success"):
                content = agent_result.get("content", "")
                result = {
                    "success": True,
                    "content": content,
                    "provider_used": agent_result.get("provider", route["provider"]),
                    "model_used": agent_result.get("model", ""),
                    "usage": agent_result.get("usage", {}),
                    "tool_calls": agent_result.get("tool_calls", []),
                    "total_turns": agent_result.get("total_turns", 1),
                    "cost_usd": agent_result.get("cost_usd", 0),
                    "route": route
                }
            else:
                result = {
                    "success": False,
                    "content": f"LLM 调用失败: {agent_result.get('content', '未知错误')}",
                    "provider_used": route["provider"],
                    "route": route
                }
        except Exception as e:
            result = {
                "success": False,
                "content": f"执行出错: {str(e)}",
                "provider_used": route["provider"],
                "route": route
            }
        
        # 记录到记忆（感知优先）
        if task.get("content"):
            self.memory.add_memory(
                content=f"用户任务: {task['content'][:200]}",
                tags=["task", route["task_type"]],
                source="task"
            )
        
        # 记录到进化系统
        self.evolution.log_task(
            task=task.get("content", ""),
            result=result.get("content", ""),
            success=result.get("success", False),
            task_type=route["task_type"],
            complexity=route["complexity"]
        )
        
        # 检查是否需要反思
        if self.evolution.should_reflect(self.task_count):
            insights = self.evolve()
            result["insights"] = insights
        
        return result
    
    def evolve(self) -> Dict[str, Any]:
        """
        自我反思和进化
        """
        print("\n[Artemis] 🔄 触发自我反思...")
        
        # 执行反思
        reflection = self.evolution.reflect()
        
        # 检测技能缺口
        gaps = self.evolution.detect_skill_gaps()
        
        # 生成改进建议
        insights = self.evolution.generate_insights(gaps)
        
        # 记录反思结果
        self.memory.add_memory(
            content=f"反思: {insights.get('summary', '完成了反思')}",
            tags=["reflection", "evolution"],
            source="evolution"
        )
        
        print(f"[Artemis] ✓ 反思完成: {insights.get('summary', '')}")
        
        return insights
    
    # ==================== 交互接口 ====================
    
    def chat(self, message: str, image: Optional[str] = None) -> str:
        """
        对话接口
        
        Args:
            message: 用户消息
            image: 可选的图片路径或 URL
            
        Returns:
            响应内容
        """
        task = {"content": message}
        if image:
            task["image"] = image
            
        result = self.run_task(task)
        return result.get("content", "处理中...")
    
    def remember(self, query: str, top_k: int = 5) -> list:
        """
        搜索记忆
        
        Args:
            query: 查询文本
            top_k: 返回数量
            
        Returns:
            相关记忆列表
        """
        return self.memory.search_memories(query, top_k)
    
    def get_user_profile(self) -> Dict[str, Any]:
        """获取用户画像"""
        return self.memory.get_user_profile()
    
    def set_provider(self, provider: str) -> bool:
        """
        切换 LLM provider（供 Telegram 命令调用）
        
        Args:
            provider: provider 名称（minimax/openrouter/deepseek/anthropic/google/auto）
            
        Returns:
            是否切换成功
        """
        if provider == "auto":
            self.current_provider = "auto"
            print("[Artemis] 已切换为 auto 模式（自动选择）")
            return True
        
        if self.llm and self.llm.is_provider_available(provider):
            self.current_provider = provider
            print(f"[Artemis] 已切换为 {provider}")
            return True
        else:
            available = self.llm.get_available_providers() if self.llm else []
            print(f"[Artemis] {provider} 不可用，可用: {available}")
            return False
    
    # ==================== 技能系统 ====================
    
    def list_skills(self) -> list:
        """列出可用技能"""
        skills_dir = BASE_DIR / self.config["skills"]["directory"]
        if not skills_dir.exists():
            return []
        
        skills = []
        for item in skills_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                skills.append(item.name)
        return skills
    
    def load_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        加载技能
        
        Args:
            skill_name: 技能目录名
            
        Returns:
            技能配置字典
        """
        skill_path = BASE_DIR / self.config["skills"]["directory"] / skill_name / "SKILL.md"
        if not skill_path.exists():
            return None
            
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        return {"name": skill_name, "content": content}
    
    # ==================== 工作空间 ====================
    
    def read_agents_md(self) -> str:
        """读取 AGENTS.md"""
        agents_path = BASE_DIR / self.config["workspace"]["path"] / self.config["workspace"]["agents_md"]
        if agents_path.exists():
            with open(agents_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""


# ==================== 便捷函数 ====================

def create_instance() -> Artemis:
    """创建 Artemis 实例"""
    agent = Artemis()
    agent.initialize()
    return agent


# ==================== 主入口 ====================

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
        # 仅启动 Cron 调度器（后台运行）
        print("\n[Artemis] 启动 Cron 调度器（后台）...")
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
    
    elif args.tui:
        # 启动 TUI 界面
        from tui import TUIBootstrap
        print("\n[Artemis] 启动 TUI 界面...")
        TUIBootstrap.launch(agent)
    
    else:
        # 默认：CLI 交互模式
        print("\n[Artemis] 交互模式（输入 /help 查看命令）")
        print("提示：使用 --tui 启动图形界面，--daemon 后台运行 Cron\n")
        
        while True:
            try:
                user_input = input("\n你: ").strip()
                if not user_input:
                    continue
                if user_input in ["/exit", "/quit"]:
                    print("👋 再见！")
                    break
                if user_input == "/help":
                    print("\n命令：")
                    print("  /tui       切换到 TUI 图形界面")
                    print("  /skills    查看可用技能")
                    print("  /cron      查看定时任务")
                    print("  /addcron   添加定时任务")
                    print("  /model     查看/切换模型")
                    print("  /history   查看对话历史")
                    print("  /memory    搜索记忆")
                    print("  /cost     查看累计成本")
                    print("  /evolve   自我进化（基于最近任务历史）")
                    print("  /propose  预览进化提议（不执行）")
                    print("  /exit     退出")
                    continue
                if user_input == "/tui":
                    from tui import TUIBootstrap
                    TUIBootstrap.launch(agent)
                    break
                if user_input == "/skills":
                    skills = agent.list_skills()
                    print(f"\n可用技能：{skills}")
                    continue
                if user_input == "/cron":
                    jobs = agent.cron.list_jobs()
                    print(f"\n定时任务 ({len(jobs)} 个)：")
                    for j in jobs:
                        print(f"  • {j.name or j.job_id} | {j.schedule} | {'🟢' if j.enabled else '🔴'}")
                    continue
                if user_input == "/model":
                    print(f"\n当前模型: {agent.current_provider}")
                    print(f"可用模型: {agent.llm.get_available_providers()}")
                    continue
                if user_input == "/cost":
                    print(f"\n{agent.cost_tracker.summary()}")
                    continue
                if user_input == "/propose":
                    print("\n[Evolution] 🔍 预览进化提议...")
                    proposal = agent.evolution.propose()
                    print(f"\n标题: {proposal.get('title', 'N/A')}")
                    print(f"描述: {proposal.get('description', 'N/A')}")
                    print(f"改动数: {len(proposal.get('changes', []))}")
                    print(f"置信度: {proposal.get('confidence', 0):.0%}")
                    print(f"风险等级: {proposal.get('risk_level', 'unknown')}")
                    for i, c in enumerate(proposal.get("changes", [])):
                        print(f"  [{i+1}] {c.get('file', '?')} — {c.get('reason', c.get('action', '?'))}")
                    continue
                if user_input == "/evolve":
                    print("\n[Evolution] 🔄 开始自我进化（低风险改动自动执行）...")
                    result = agent.evolution.evolve(failed_only=False, auto_approve_low_risk=True)
                    evolved = result.get("evolved", False)
                    title = result.get("title", "N/A")
                    changes = result.get("changes", [])
                    rollback = result.get("rollback_done", False)
                    error = result.get("error", "")
                    
                    if evolved:
                        print(f"\n✅ 进化成功！")
                        print(f"   标题: {title}")
                        print(f"   改动: {', '.join(changes)}")
                    elif rollback:
                        print(f"\n❌ 进化失败，已自动回滚")
                        print(f"   标题: {title}")
                        print(f"   错误: {error}")
                    else:
                        print(f"\n⚪ 本次未进化")
                        print(f"   原因: {title}")
                        if result.get("approval_needed"):
                            print(f"   需要人工批准的高风险改动: {len(result['approval_needed'])} 个")
                    continue
                if user_input.startswith("/addcron "):
                    parts = user_input[9:].split(" ", 2)
                    if len(parts) >= 3:
                        name, schedule, prompt = parts
                        job = agent.cron.create_job(prompt, schedule, name)
                        print(f"✅ 已创建: {job.job_id}")
                    else:
                        print("用法: /addcron <name> <schedule> <prompt>")
                    continue
                
                # 普通对话
                response = agent.chat(user_input)
                print(f"\nArtemis: {response}")
                
            except KeyboardInterrupt:
                print("\n\n👋 再见！")
                break
            except EOFError:
                break
