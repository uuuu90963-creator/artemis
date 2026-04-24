#!/usr/bin/env python3
"""
Artemis 自我进化 - LLM 进化提议器
分析任务历史，用 LLM 生成具体的代码修改建议
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


class EvolutionProposer:
    """
    LLM 驱动的进化提议器
    
    输入：任务历史（成功/失败日志）
    输出：具体的代码修改提议（可以被 SafeCodeWriter 执行）
    
    提议格式：
    {
        "title": "优化 router.py 的路由决策逻辑",
        "description": "根据失败日志分析，router 在处理 vision 任务时总是选 minimax...",
        "changes": [
            {
                "file": "artemis/router.py",
                "action": "modify",        # "modify" | "create" | "delete"
                "reason": "修复 vision 任务路由到错误 provider 的 bug",
                "content": "...新的完整文件内容...",
                # 或者用 diff:
                "diff": "@@ -10,5 +10,7 @@..."
            }
        ],
        "confidence": 0.85,               # 置信度（0-1）
        "risk_level": "low",             # "low" | "medium" | "high"
        "expected_improvement": "vision 任务成功率从 60% 提升到 90%"
    }
    """
    
    SYSTEM_PROMPT = """你是一位 AI 系统优化专家（Artemis 的"灵魂工程师"）。
你的任务是根据任务执行日志，生成具体、可执行的代码修改建议。

核心原则：
1. 建议必须精确：给出完整的新文件内容（modify 模式）或完整的新文件（create 模式）
2. 改动越小越好：优先改局部，不改整体
3. 安全第一：禁止使用 os.system、subprocess、eval、exec 等危险操作
4. 每次进化最多改 2 个文件，每个文件最多改动 50 行以内
5. 改动必须向后兼容：不能破坏现有功能

分析维度：
- 失败模式：同类任务反复失败说明有系统性 bug
- 性能瓶颈：某类任务耗时过长，可能是模型选择不当
- 能力缺口：某类任务从未成功过，说明缺少相应技能
- 用户偏好：用户总用某个功能，说明这是核心路径，应该优化

输出格式（严格 JSON）：
{
    "title": "一句话描述优化目标",
    "description": "详细说明为什么需要这个改动，基于什么观察",
    "changes": [
        {
            "file": "相对路径，如 artemis/router.py",
            "action": "modify",
            "reason": "这个文件为什么需要改",
            "content": "完整的新文件内容（Python 代码）"
        }
    ],
    "confidence": 0.0-1.0,
    "risk_level": "low/medium/high",
    "expected_improvement": "改动后的预期效果"
}

如果没有发现需要改进的地方，返回：
{
    "title": "无需进化",
    "description": "系统运行正常，无需修改",
    "changes": [],
    "confidence": 0.0,
    "risk_level": "low",
    "expected_improvement": "N/A"
}"""

    def __init__(self, project_root: Path, llm_client=None, provider: str = "minimax"):
        self.project_root = Path(project_root)
        self.llm = llm_client
        self.provider = provider
    
    def generate_proposal(self, task_history: List[Dict[str, Any]],
                          failed_only: bool = False) -> Dict[str, Any]:
        """
        基于任务历史生成进化提议
        
        Args:
            task_history: 任务历史列表
            failed_only: 是否只看失败的任务
        """
        # 过滤任务
        if failed_only:
            tasks = [t for t in task_history if not t.get("success")]
        else:
            tasks = task_history[-10:]  # 最近 10 个
        
        if not tasks:
            return self._no_evolution_needed("暂无任务历史数据")
        
        # 格式化任务摘要
        task_summary = self._format_task_summary(tasks)
        
        # 构建 LLM prompt
        user_prompt = f"""## Artemis 任务执行历史（最近 {len(tasks)} 个）：

{task_summary}

## 可修改的模块列表（安全范围）：
{self._get_modifiable_modules()}

请分析以上任务历史，找出：
1. 系统性的 bug（同类任务重复失败）
2. 可以优化的地方（性能、路由、工具调用）
3. 缺失的能力（可以加新技能/工具）

如果发现问题，请生成具体的代码修改建议。"""

        # 调用 LLM
        if not self.llm:
            return self._no_evolution_needed("LLM 客户端未配置")
        
        try:
            result = self.llm.chat(
                prompt=None,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                provider=self.provider,
                stream=False,
            )
            
            if not result.get("success"):
                return self._no_evolution_needed(f"LLM 调用失败: {result.get('error')}")
            
            content = result.get("content", "")
            
            # 解析 JSON
            proposal = self._parse_llm_response(content)
            
            if not proposal:
                return self._no_evolution_needed("无法解析 LLM 响应")
            
            # 校验提议
            valid, errors = self._validate_proposal(proposal)
            if not valid:
                proposal["title"] = "提议被安全策略拦截"
                proposal["errors"] = errors
            
            return proposal
        
        except Exception as e:
            return self._no_evolution_needed(f"进化提议生成异常: {e}")
    
    def _format_task_summary(self, tasks: List[Dict[str, Any]]) -> str:
        """格式化任务历史"""
        lines = []
        for i, t in enumerate(tasks):
            status = "✅" if t.get("success") else "❌"
            lines.append(
                f"[{i+1}] {status} | "
                f"类型: {t.get('task_type', '?')} | "
                f"复杂度: {t.get('complexity', '?')}\n"
                f"    任务: {t.get('task', '')[:100]}\n"
                f"    结果: {t.get('result', '')[:100]}"
            )
        return "\n".join(lines)
    
    def _get_modifiable_modules(self) -> str:
        """获取可修改模块列表"""
        allowed_dirs = ["artemis", "skills", "plugins"]
        modules = []
        for d in allowed_dirs:
            p = self.project_root / d
            if p.exists():
                for f in p.rglob("*.py"):
                    rel = f.relative_to(self.project_root)
                    modules.append(f"  - {rel}")
        return "\n".join(modules[:30])  # 限制数量
    
    def _parse_llm_response(self, content: str) -> Optional[Dict[str, Any]]:
        """从 LLM 响应中解析 JSON 提议"""
        # 尝试找 ```json ... ``` 块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试找 JSON 对象（可能前后有文字）
            try:
                start = content.index('{')
                end = content.rindex('}') + 1
                return json.loads(content[start:end])
            except (ValueError, json.JSONDecodeError):
                return None
    
    def _validate_proposal(self, proposal: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        验证提议是否在安全范围内
        """
        errors = []
        
        # 检查文件路径
        for change in proposal.get("changes", []):
            file_path = change.get("file", "")
            
            # 检查路径格式
            if not file_path:
                errors.append(f"change 缺少 file 字段")
                continue
            
            # 必须是以允许的目录开头
            allowed_prefixes = ("artemis/", "skills/", "plugins/")
            if not any(file_path.startswith(p) for p in allowed_prefixes):
                errors.append(f"文件 '{file_path}' 不在允许的目录内")
            
            # 检查扩展名
            if not any(file_path.endswith(ext) for ext in [".py", ".yaml", ".yml", ".json", ".md"]):
                errors.append(f"文件 '{file_path}' 类型不在允许列表")
        
        return len(errors) == 0, errors
    
    def _no_evolution_needed(self, reason: str) -> Dict[str, Any]:
        """返回"无需进化"的空提议"""
        return {
            "title": "无需进化",
            "description": reason,
            "changes": [],
            "confidence": 0.0,
            "risk_level": "low",
            "expected_improvement": "N/A",
        }
