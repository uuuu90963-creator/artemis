#!/usr/bin/env python3
"""
Artemis 技能加载器
按需加载技能的完整信息
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
import sys
sys.path.insert(0, str(Path(__file__).parent))
from skill_manager import SkillManager, Skill


class SkillLoader:
    """技能加载器 - 按需加载技能"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.manager = SkillManager(skills_dir)
        self._loaded_cache: Dict[str, Dict[str, Any]] = {}

    def load_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        加载某个技能的完整信息
        包括 SKILL.md 内容 + script.py（如果存在）
        """
        skill = self.manager.get_skill(skill_name)
        if not skill:
            return None

        skill_path = self.skills_dir / skill.path

        result = {
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "trigger_keywords": skill.trigger_keywords,
            "enabled": skill.enabled,
            "path": str(skill_path),
            "files": {}
        }

        # 加载 SKILL.md
        skill_md = skill_path / "SKILL.md"
        if skill_md.exists():
            result["files"]["SKILL.md"] = skill_md.read_text(encoding="utf-8")

        # 加载 script.py（如果存在）
        script_py = skill_path / "script.py"
        if script_py.exists():
            result["files"]["script.py"] = script_py.read_text(encoding="utf-8")

        self._loaded_cache[skill_name] = result
        return result

    def auto_load_for_task(self, task_text: str) -> List[Dict[str, Any]]:
        """
        根据任务自动加载相关技能
        返回加载的技能列表
        """
        suggestions = self.manager.suggest_skills_for_task(task_text)
        loaded = []

        for skill in suggestions[:3]:  # 最多加载3个
            data = self.load_skill(skill.name)
            if data:
                loaded.append(data)

        return loaded

    def execute_skill_script(
        self, skill_name: str, function_name: str, **kwargs
    ) -> Optional[Any]:
        """
        执行技能的脚本中的函数
        技能脚本需要定义: def execute(**kwargs) -> Any
        """
        skill_data = self.load_skill(skill_name)
        if not skill_data or "script.py" not in skill_data.get("files", {}):
            return None

        script_content = skill_data["files"]["script.py"]

        # 写入临时文件执行
        import tempfile
        import sys

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(script_content)
            temp_path = f.name

        try:
            # 注入 kwargs 到执行上下文
            import importlib.util
            spec = importlib.util.spec_from_file_location("skill_module", temp_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "execute"):
                return module.execute(**kwargs)
            elif hasattr(module, function_name):
                return getattr(module, function_name)(**kwargs)
        except Exception as e:
            print(f"技能执行失败: {skill_name}.{function_name}: {e}")
            return None
        finally:
            Path(temp_path).unlink(missing_ok=True)

        return None

    def list_available_functions(self, skill_name: str) -> List[str]:
        """列出技能脚本中可用的函数"""
        skill_data = self.load_skill(skill_name)
        if not skill_data or "script.py" not in skill_data.get("files", {}):
            return []

        import ast, re

        script = skill_data["files"]["script.py"]
        try:
            tree = ast.parse(script)
            return [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        except:
            return []

    def get_skill_help(self, skill_name: str) -> Optional[str]:
        """获取技能的帮助信息"""
        skill_data = self.load_skill(skill_name)
        if not skill_data:
            return None

        lines = [f"## {skill.name} (v{skill.version})"]
        lines.append(f"{skill.description}\n")
        lines.append("**触发关键词**: " + ", ".join(skill.trigger_keywords))

        if "SKILL.md" in skill_data.get("files", {}):
            lines.append("\n---\n")
            lines.append(skill_data["files"]["SKILL.md"])

        return "\n".join(lines)


if __name__ == "__main__":
    from pathlib import Path
    loader = SkillLoader(Path("/root/.hermes/artemis/skills"))
    print("自动加载测试（医学文献任务）:")
    loaded = loader.auto_load_for_task("帮我查一下 PMID 40845039 这篇文献")
    for s in loaded:
        print(f"  - {s['name']}: {s['description']}")
