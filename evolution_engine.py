#!/usr/bin/env python3
"""
Artemis 自我进化系统 v2.0
记录任务 → LLM反思 → 提议进化 → 安全审查 → 自动执行/申请批准 → 验证 → 回滚保护

核心类：
- EvolutionEngine: 主协调器
- EvolutionProposer: LLM 生成进化提议
- EvolutionPolicy: 安全策略审查
- SafeCodeWriter: 安全代码写入
- SelfTester: 自动测试验证
- RollbackManager: Git 回滚保护
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict


class EvolutionEngine:
    """
    进化引擎类
    通过日志记录和 LLM 反思实现真正的自我进化
    """
    
    # LLM 反思用的系统提示词
    REFLECTION_SYSTEM_PROMPT = """你是一位专业的 AI 助手优化专家。你的任务是分析 AI 助手（Artemis）的任务执行日志，生成高质量的观察和改进建议。

分析维度：
1. 任务成功率与失败模式
2. 任务类型分布是否合理
3. 路由策略是否最优（应该用便宜快速的模型还是贵但精准的模型）
4. 工具调用链路是否顺畅
5. 是否有能力缺口需要补充新技能
6. 医学/临床场景下是否有特殊风险

请始终用中文输出。"""

    def __init__(self, log_dir: Path, 反思_after_tasks: int = 3,
                 llm_client=None, provider: str = "minimax"):
        """
        初始化进化引擎
        
        Args:
            log_dir: 日志目录
            反思_after_tasks: 每N个任务后反思一次
            llm_client: 可选的 LLM 客户端（用于真实反思）
            provider: LLM 提供商 (minimax/deepseek/openrouter)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.反思_after_tasks = 反思_after_tasks
        
        # LLM 客户端（用于真实反思）
        self.llm = llm_client
        self.llm_provider = provider
        
        # 任务历史
        self.task_history: List[Dict[str, Any]] = []
        
        # 统计数据
        self.stats = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "by_type": defaultdict(lambda: {"total": 0, "success": 0}),
            "by_complexity": defaultdict(lambda: {"total": 0, "success": 0})
        }
        
        # 当前月份日志文件
        self._current_log_file = None
        self._get_log_file()
    
    def _get_log_file(self) -> Path:
        """获取当前月份的日志文件"""
        now = datetime.now()
        filename = f"{now.year}-{now.month:02d}.jsonl"
        self._current_log_file = self.log_dir / filename
        return self._current_log_file
    
    def _load_recent_logs(self, months: int = 1) -> List[Dict[str, Any]]:
        """加载最近几个月的日志"""
        logs = []
        now = datetime.now()
        
        for i in range(months):
            month = now.month - i
            year = now.year
            if month <= 0:
                month += 12
                year -= 1
            
            log_file = self.log_dir / f"{year}-{month:02d}.jsonl"
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            logs.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            continue
        
        return logs
    
    def log_task(self, task: str, result: str, success: bool,
                 task_type: str = "unknown", complexity: str = "medium"):
        """
        记录任务执行
        
        Args:
            task: 任务描述
            result: 执行结果
            success: 是否成功
            task_type: 任务类型
            complexity: 复杂度
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "task": task[:500] if task else "",  # 截断过长的任务
            "result": result[:500] if result else "",
            "success": success,
            "task_type": task_type,
            "complexity": complexity
        }
        
        # 记录到历史
        self.task_history.append(entry)
        self.stats["total_tasks"] += 1
        if success:
            self.stats["successful_tasks"] += 1
        else:
            self.stats["failed_tasks"] += 1
        
        self.stats["by_type"][task_type]["total"] += 1
        if success:
            self.stats["by_type"][task_type]["success"] += 1
        
        self.stats["by_complexity"][complexity]["total"] += 1
        if success:
            self.stats["by_complexity"][complexity]["success"] += 1
        
        # 写入日志文件
        with open(self._current_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def should_reflect(self, task_count: int) -> bool:
        """
        判断是否应该触发反思
        
        Args:
            task_count: 当前任务数
            
        Returns:
            是否应该反思
        """
        return task_count > 0 and task_count % self.反思_after_tasks == 0
    
    def reflect(self) -> Dict[str, Any]:
        """
        触发反思
        分析最近的任务历史，生成反思报告
        """
        print("[Evolution] 开始反思...")
        
        # 获取最近日志
        recent_logs = self._load_recent_logs()
        
        if not recent_logs:
            return {"status": "no_data", "message": "暂无足够数据进行反思"}
        
        # 分析最近任务
        recent_tasks = recent_logs[-self.反思_after_tasks:] if len(recent_logs) >= self.反思_after_tasks else recent_logs
        
        # 统计信息
        success_rate = sum(1 for t in recent_tasks if t.get("success")) / len(recent_tasks) if recent_tasks else 0
        
        # 失败任务分析
        failures = [t for t in recent_tasks if not t.get("success")]
        failure_reasons = []
        if failures:
            for f in failures:
                failure_reasons.append({
                    "task": f.get("task", "")[:100],
                    "timestamp": f.get("timestamp")
                })
        
        # 反思报告
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "tasks_analyzed": len(recent_tasks),
            "success_rate": round(success_rate * 100, 1),
            "failures": failure_reasons,
            "observations": self._generate_observations(recent_tasks),
            "recommendations": self._generate_recommendations(recent_tasks, success_rate)
        }
        
        # 保存反思日志
        reflection_file = self.log_dir / f"reflection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(reflection_file, "w", encoding="utf-8") as f:
            json.dump(reflection, f, ensure_ascii=False, indent=2)
        
        print(f"[Evolution] 反思完成: 成功率 {reflection['success_rate']}%")
        
        return reflection
    
    def _generate_observations(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """
        生成观察结果 — LLM 驱动
        用真实 LLM 分析任务历史，发现模板匹配发现不了的深层模式
        """
        # 如果没有 LLM 客户端，降级到模板版本
        if not self.llm:
            return self._generate_observations_template(tasks)
        
        # 构建分析任务摘要
        task_summary = []
        for i, t in enumerate(tasks):
            status = "✅" if t.get("success") else "❌"
            task_summary.append(
                f"[{i+1}] {status} | 类型: {t.get('task_type','?')} | "
                f"复杂度: {t.get('complexity','?')} | "
                f"任务: {t.get('task','')[:80]} | "
                f"结果: {t.get('result','')[:60]}"
            )
        
        user_prompt = f"""## 最近 {len(tasks)} 个任务执行记录：

{chr(10).join(task_summary)}

请分析以上任务记录，找出：
1. 成功率、失败模式的深层原因
2. 任务类型分布反映的能力倾向
3. 路由策略（用什么模型）是否最优
4. 工具调用是否有问题
5. 医学场景下是否有特殊风险或机会

请以 JSON 格式返回：
{{
  "observations": ["观察点1", "观察点2", ...]  // 3-5条有深度的观察
}}"""
        
        try:
            result = self.llm.chat(
                prompt=None,
                messages=[
                    {"role": "system", "content": self.REFLECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                provider=self.llm_provider,
                stream=False,
            )
            
            if result.get("success"):
                content = result.get("content", "")
                # 尝试从响应中提取 JSON
                try:
                    # 找 ```json ... ``` 或纯 JSON
                    import re
                    json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(1))
                    else:
                        # 尝试直接解析
                        data = json.loads(content)
                    obs = data.get("observations", [])
                    if obs:
                        print(f"[Evolution] LLM 观察生成: {len(obs)} 条")
                        return obs
                except (json.JSONDecodeError, AttributeError):
                    # JSON 解析失败，降级
                    pass
        except Exception as e:
            print(f"[Evolution] LLM 观察生成失败: {e}，降级到模板")
        
        return self._generate_observations_template(tasks)
    
    def _generate_observations_template(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """生成观察结果 — 模板版本（LLM 不可用时的降级方案）"""
        observations = []
        
        # 分析任务类型分布
        type_counts = defaultdict(int)
        for t in tasks:
            type_counts[t.get("task_type", "unknown")] += 1
        
        dominant_type = max(type_counts.items(), key=lambda x: x[1])
        if dominant_type[1] > len(tasks) * 0.5:
            observations.append(f"近期任务以 {dominant_type[0]} 类型为主")
        
        # 分析复杂度
        complexity_counts = defaultdict(int)
        for t in tasks:
            complexity_counts[t.get("complexity", "medium")] += 1
        
        if complexity_counts.get("critical", 0) > 0:
            observations.append("处理过高复杂度任务，需要注意资源分配")
        
        # 分析任务长度
        avg_length = sum(len(t.get("task", "")) for t in tasks) / len(tasks) if tasks else 0
        if avg_length > 300:
            observations.append("任务复杂度有上升趋势")
        
        return observations
    
    def _generate_recommendations(self, tasks: List[Dict[str, Any]], success_rate: float) -> List[str]:
        """
        生成改进建议 — LLM 驱动
        基于任务历史，LLM 生成真正可操作的改进建议
        """
        # 如果没有 LLM 客户端，降级到模板版本
        if not self.llm:
            return self._generate_recommendations_template(tasks, success_rate)
        
        task_summary = []
        failures = []
        for i, t in enumerate(tasks):
            status = "✅" if t.get("success") else "❌"
            task_summary.append(f"[{i+1}] {status} | {t.get('task','')[:60]} | {t.get('result','')[:50]}")
            if not t.get("success"):
                failures.append(f"  失败: {t.get('task','')[:60]}")
        
        user_prompt = f"""## 最近 {len(tasks)} 个任务执行记录：

{chr(10).join(task_summary)}

## 失败任务：
{chr(10).join(failures) if failures else "无失败任务"}

## 基础统计：
- 成功率: {success_rate*100:.1f}%
- 总任务数: {len(tasks)}
- 失败数: {len(failures)}

请作为 AI 优化专家，给出真正可操作的改进建议：
1. 路由策略优化（什么时候该用便宜模型，什么时候该用贵的精准模型）
2. 工具/技能层面需要补充什么
3. 失败任务应该如何改进处理流程
4. 是否有系统性风险（医学场景尤其重要）

请以 JSON 格式返回：
{{
  "recommendations": ["建议1", "建议2", ...]  // 3-5条具体可执行的建议
}}"""
        
        try:
            result = self.llm.chat(
                prompt=None,
                messages=[
                    {"role": "system", "content": self.REFLECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                provider=self.llm_provider,
                stream=False,
            )
            
            if result.get("success"):
                content = result.get("content", "")
                try:
                    import re
                    json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(1))
                    else:
                        data = json.loads(content)
                    recs = data.get("recommendations", [])
                    if recs:
                        print(f"[Evolution] LLM 建议生成: {len(recs)} 条")
                        return recs
                except (json.JSONDecodeError, AttributeError):
                    pass
        except Exception as e:
            print(f"[Evolution] LLM 建议生成失败: {e}，降级到模板")
        
        return self._generate_recommendations_template(tasks, success_rate)
    
    def _generate_recommendations_template(self, tasks: List[Dict[str, Any]], success_rate: float) -> List[str]:
        """生成改进建议 — 模板版本（LLM 不可用时的降级方案）"""
        recommendations = []
        
        if success_rate < 0.7:
            recommendations.append("注意：近期成功率偏低，建议检查路由策略")
        
        failures_by_type = defaultdict(int)
        for t in tasks:
            if not t.get("success"):
                failures_by_type[t.get("task_type", "unknown")] += 1
        
        for fail_type, count in failures_by_type.items():
            if count > 0:
                recommendations.append(f"{fail_type} 类型任务需要优化处理流程")
        
        return recommendations
    
    def detect_skill_gaps(self) -> List[Dict[str, Any]]:
        """
        检测技能缺口
        当遇到处理不好的任务时，记录需要什么新技能
        """
        gaps = []
        
        # 加载最近失败的任务
        recent_logs = self._load_recent_logs(months=1)
        recent_failures = [t for t in recent_logs[-20:] if not t.get("success")]
        
        if len(recent_failures) < 2:
            return gaps
        
        # 分析失败模式
        failure_patterns = defaultdict(list)
        for f in recent_failures:
            task_type = f.get("task_type", "unknown")
            failure_patterns[task_type].append(f.get("task", "")[:100])
        
        # 生成技能缺口报告
        for fail_type, tasks in failure_patterns.items():
            if len(tasks) >= 2:
                gaps.append({
                    "type": fail_type,
                    "gap_count": len(tasks),
                    "sample_tasks": tasks[:3],
                    "suggested_skill": self._suggest_skill_for_type(fail_type)
                })
        
        return gaps
    
    def _suggest_skill_for_type(self, task_type: str) -> Optional[str]:
        """为任务类型建议技能"""
        skill_mapping = {
            "medical": "medical-guidelines",
            "vision": "image-analysis",
            "code": "code-development",
            "text_complex": "advanced-reasoning"
        }
        return skill_mapping.get(task_type)
    
    def generate_insights(self, gaps: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        生成改进建议
        综合分析后给出具体行动建议
        """
        insights = {
            "summary": "",
            "strengths": [],
            "improvements": [],
            "next_actions": []
        }
        
        # 分析成功率趋势
        recent_logs = self._load_recent_logs(months=1)
        if len(recent_logs) >= 10:
            recent_10 = recent_logs[-10:]
            recent_success = sum(1 for t in recent_10 if t.get("success")) / 10
            
            if recent_success >= 0.9:
                insights["summary"] = "表现优秀，继续保持"
                insights["strengths"].append("任务完成率高")
            elif recent_success >= 0.7:
                insights["summary"] = "整体稳定，部分场景需优化"
                insights["improvements"].append("关注失败率较高的任务类型")
            else:
                insights["summary"] = "需要重点改进"
                insights["improvements"].append("建议检查路由和执行流程")
        
        # 基于技能缺口
        if gaps:
            for gap in gaps:
                insights["improvements"].append(
                    f"{gap['type']} 类任务处理需要加强 (失败 {gap['gap_count']} 次)"
                )
                if gap.get("suggested_skill"):
                    insights["next_actions"].append(
                        f"学习技能: {gap['suggested_skill']}"
                    )
        
        # 默认建议
        if not insights["summary"]:
            insights["summary"] = "系统运行正常"
        
        return insights
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_tasks": self.stats["total_tasks"],
            "success_rate": (
                self.stats["successful_tasks"] / self.stats["total_tasks"]
                if self.stats["total_tasks"] > 0 else 0
            ),
            "by_type": dict(self.stats["by_type"]),
            "by_complexity": dict(self.stats["by_complexity"])
        }
    
    def export_logs(self, output_path: Path, months: int = 3):
        """导出日志到指定文件"""
        logs = self._load_recent_logs(months=months)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
        
        return len(logs)
    
    # ==================== 自我进化核心 ====================
    
    def evolve(self, failed_only: bool = False,
               auto_approve_low_risk: bool = True) -> Dict[str, Any]:
        """
        执行完整的自我进化流程
        
        流程：
        1. 加载任务历史
        2. LLM 生成进化提议
        3. 安全策略审查
        4. Git 快照备份
        5. 申请批准 / 自动执行低风险改动
        6. 应用修改
        7. 自动测试验证
        8. 成功则固化，失败则回滚
        
        Args:
            failed_only: 是否只分析失败任务
            auto_approve_low_risk: 低风险改动是否自动执行（不需人审批）
        
        Returns: {
            "evolved": bool,           # 是否执行了进化
            "title": str,              # 进化标题
            "changes": [...],           # 改动的文件列表
            "test_result": {...},       # 测试结果
            "rollback_done": bool,     # 是否执行了回滚
            "approval_needed": [...]   # 需要用户批准的高风险改动
        }
        """
        print("[Evolution] 🔄 开始自我进化...")
        
        # Step 1: 加载任务历史
        recent_logs = self._load_recent_logs(months=1)
        if not recent_logs:
            return {"evolved": False, "title": "无任务历史，跳过进化", "changes": [], "test_result": {}}
        
        # 取最近 10 个任务（失败优先）
        task_history = recent_logs[-10:]
        if failed_only:
            task_history = [t for t in task_history if not t.get("success")]
        
        if len(task_history) < 2:
            return {"evolved": False, "title": "任务数不足，跳过进化", "changes": [], "test_result": {}}
        
        # Step 2: LLM 生成进化提议
        proposer = self._get_proposer()
        proposal = proposer.generate_proposal(task_history, failed_only=failed_only)
        
        # 检查是否需要进化
        if not proposal.get("changes"):
            print(f"[Evolution] ✓ {proposal.get('title', '无需进化')}")
            return {
                "evolved": False,
                "title": proposal.get("title", "无需进化"),
                "description": proposal.get("description", ""),
                "changes": [],
                "test_result": {},
            }
        
        print(f"[Evolution] 📋 提议: {proposal.get('title')}")
        print(f"[Evolution]   描述: {proposal.get('description', '')[:80]}")
        print(f"[Evolution]   置信度: {proposal.get('confidence', 0):.0%}")
        print(f"[Evolution]   风险等级: {proposal.get('risk_level', 'unknown')}")
        
        # Step 3: 安全策略审查
        from evolution.policy import EvolutionPolicy
        BASE_DIR = Path(__file__).parent.parent
        policy = EvolutionPolicy(BASE_DIR)
        
        changes_to_apply = []
        high_risk_changes = []
        
        for change in proposal.get("changes", []):
            file_path = change.get("file", "")
            allowed, reason = policy.can_modify_file(file_path)
            if not allowed:
                print(f"[Evolution] 🚫 策略拦截: {file_path} — {reason}")
                continue
            
            risk = self._assess_change_risk(change)
            if risk == "high" and not auto_approve_low_risk:
                high_risk_changes.append({**change, "risk": risk})
            else:
                changes_to_apply.append({**change, "risk": risk})
        
        # 如果全是高风险改动且用户选择不自动审批，返回需要批准的信息
        if not changes_to_apply and high_risk_changes:
            print(f"[Evolution] ⚠️ {len(high_risk_changes)} 个高风险改动需要人工批准")
            return {
                "evolved": False,
                "title": proposal.get("title"),
                "description": proposal.get("description"),
                "changes": high_risk_changes,
                "approval_needed": high_risk_changes,
                "test_result": {},
                "evolved": False,
            }
        
        if not changes_to_apply:
            return {"evolved": False, "title": "无安全改动，跳过进化", "changes": [], "test_result": {}}
        
        # Step 4: Git 快照备份
        rollback_mgr = self._get_rollback_manager(BASE_DIR)
        snapshot_id = rollback_mgr.create_snapshot(proposal.get("title", "evolution"))
        print(f"[Evolution] 📸 快照: {snapshot_id or '无（无变更）'}")
        
        # Step 5: 应用修改
        from evolution.code_writer import SafeCodeWriter
        writer = SafeCodeWriter(BASE_DIR, BASE_DIR / "evolution" / "snapshots")
        
        applied_files = []
        for change in changes_to_apply:
            file_path = change.get("file", "")
            new_content = change.get("content", "")
            
            success, msg = writer.apply_modification(file_path, new_content, policy)
            if success:
                print(f"[Evolution] ✅ {msg}")
                applied_files.append(file_path)
            else:
                print(f"[Evolution] ❌ {msg}")
        
        if not applied_files:
            print("[Evolution] 没有文件被修改，跳过进化")
            return {"evolved": False, "title": "无文件被修改", "changes": [], "test_result": {}}
        
        # Step 6: 自动测试验证
        print("[Evolution] 🧪 运行自动测试...")
        from evolution.self_tester import SelfTester
        tester = SelfTester(BASE_DIR)
        test_result = tester.full_test(applied_files)
        
        passed = test_result.get("passed", False)
        for detail in test_result.get("details", []):
            for check in detail.get("checks", []):
                status = "✅" if check["passed"] else "❌"
                print(f"[Evolution]   {status} {check['msg']}")
        
        # Step 7: 验证结果
        if not passed:
            print(f"[Evolution] 🔁 测试失败，执行回滚...")
            if snapshot_id and snapshot_id != "no_changes":
                ok, msg = rollback_mgr.rollback_to(snapshot_id)
                print(f"[Evolution]   回滚结果: {msg}")
            return {
                "evolved": False,
                "title": f"进化失败（测试未通过）: {proposal.get('title')}",
                "changes": applied_files,
                "test_result": test_result,
                "rollback_done": True,
                "error": "测试验证失败，已自动回滚",
            }
        
        # 验证通过：固化快照
        print(f"[Evolution] ✅ 进化成功！改动 {len(applied_files)} 个文件")
        
        # 保存进化记录
        self._save_evolution_record({
            "timestamp": datetime.now().isoformat(),
            "title": proposal.get("title"),
            "description": proposal.get("description"),
            "files_changed": applied_files,
            "confidence": proposal.get("confidence", 0),
            "risk_level": proposal.get("risk_level", "unknown"),
            "expected_improvement": proposal.get("expected_improvement", ""),
            "test_passed": True,
            "snapshot_id": snapshot_id,
        })
        
        return {
            "evolved": True,
            "title": proposal.get("title"),
            "description": proposal.get("description"),
            "changes": applied_files,
            "test_result": test_result,
            "rollback_done": False,
            "confidence": proposal.get("confidence", 0),
            "risk_level": proposal.get("risk_level", "unknown"),
            "expected_improvement": proposal.get("expected_improvement", ""),
        }
    
    def _assess_change_risk(self, change: Dict[str, Any]) -> str:
        """评估单个改动的风险等级"""
        file_path = change.get("file", "")
        content = change.get("content", "")
        risk = "low"
        
        # 文件大小
        if len(content) > 10000:
            risk = "medium"
        if len(content) > 30000:
            risk = "high"
        
        # 高风险文件
        if any(kw in file_path for kw in ["agent.py", "llm.py", "artemis.py"]):
            risk = max(risk, "medium")
        
        # 危险代码模式
        danger_patterns = ["subprocess", "eval", "exec", "system", "os.chmod", "shutil.rmtree"]
        if any(p in content for p in danger_patterns):
            risk = "high"
        
        return risk
    
    def _get_proposer(self):
        """获取或创建提议器"""
        BASE_DIR = Path(__file__).parent.parent
        return EvolutionProposer(
            project_root=BASE_DIR,
            llm_client=self.llm,
            provider=self.llm_provider,
        )
    
    def _get_rollback_manager(self, project_root: Path):
        """获取或创建回滚管理器"""
        snapshot_dir = project_root / "evolution" / "snapshots"
        return RollbackManager(project_root, snapshot_dir)
    
    def _save_evolution_record(self, record: Dict[str, Any]):
        """保存进化记录"""
        record_file = Path(__file__).parent / "evolution_records.jsonl"
        with open(record_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    def get_evolution_history(self) -> List[Dict[str, Any]]:
        """获取进化历史"""
        record_file = Path(__file__).parent / "evolution_records.jsonl"
        if not record_file.exists():
            return []
        
        records = []
        with open(record_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        return records
    
    def propose(self) -> Dict[str, Any]:
        """
        轻量版：只生成提议，不执行（用于预览）
        """
        recent_logs = self._load_recent_logs(months=1)
        if not recent_logs:
            return {"title": "无任务历史", "changes": [], "confidence": 0}
        
        proposer = self._get_proposer()
        return proposer.generate_proposal(recent_logs[-10:])


# ==================== 单元测试 ====================

if __name__ == "__main__":
    print("[EvolutionEngine] 运行单元测试...\n")
    
    # 创建测试目录
    import tempfile
    test_dir = Path(tempfile.mkdtemp())
    
    engine = EvolutionEngine(log_dir=test_dir, 反思_after_tasks=3)
    
    # 模拟任务记录
    print("1. 记录任务:")
    engine.log_task("查询天气", "返回天气信息", True, "text_simple", "simple")
    engine.log_task("分析医学影像", "发现异常", True, "vision", "complex")
    engine.log_task("编写排序算法", "代码完成", False, "code", "medium")
    print(f"   统计: {engine.get_stats()}")
    
    print("\n2. 检查是否需要反思 (任务数=3):")
    print(f"   应该反思: {engine.should_reflect(3)}")
    
    print("\n3. 触发反思:")
    reflection = engine.reflect()
    print(f"   反思结果: {reflection.get('summary')}")
    
    print("\n4. 检测技能缺口:")
    gaps = engine.detect_skill_gaps()
    print(f"   发现缺口: {len(gaps)}")
    
    print("\n5. 生成洞察:")
    insights = engine.generate_insights(gaps)
    print(f"   {insights}")
    
    # 清理
    import shutil
    shutil.rmtree(test_dir)
    
    print("\n[EvolutionEngine] ✓ 测试完成!")
