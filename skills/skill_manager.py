#!/usr/bin/env python3
"""
Artemis 技能管理器
负责技能的注册、发现、加载、启用/禁用
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class Skill:
    name: str
    version: str
    description: str
    trigger_keywords: List[str]
    enabled: bool
    path: str
    loaded: bool = False


class SkillManager:
    """技能管理器"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.registry_path = skills_dir / "registry.json"
        self.registry: Dict[str, Any] = {}
        self._load_registry()

    def _load_registry(self):
        """加载技能注册表"""
        if self.registry_path.exists():
            with open(self.registry_path, "r", encoding="utf-8") as f:
                self.registry = json.load(f)
        else:
            self.registry = {"version": "1.0.0", "skills": []}

    def _save_registry(self):
        """保存技能注册表"""
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(self.registry, f, ensure_ascii=False, indent=2)

    def list_skills(self) -> List[Skill]:
        """列出所有技能"""
        skills = []
        for s in self.registry.get("skills", []):
            skill_dir = self.skills_dir / s["path"]
            skills.append(Skill(
                name=s["name"],
                version=s["version"],
                description=s["description"],
                trigger_keywords=s.get("trigger_keywords", []),
                enabled=s.get("enabled", True),
                path=s["path"],
                loaded=skill_dir.exists() and (skill_dir / "SKILL.md").exists()
            ))
        return skills

    def get_skill(self, name: str) -> Optional[Skill]:
        """获取指定技能"""
        for skill in self.list_skills():
            if skill.name == name:
                return skill
        return None

    def enable_skill(self, name: str) -> bool:
        """启用技能"""
        for s in self.registry.get("skills", []):
            if s["name"] == name:
                s["enabled"] = True
                self._save_registry()
                return True
        return False

    def disable_skill(self, name: str) -> bool:
        """禁用技能"""
        for s in self.registry.get("skills", []):
            if s["name"] == name:
                s["enabled"] = False
                self._save_registry()
                return True
        return False

    def check_skill_availability(self, task_type: str) -> List[str]:
        """检查某任务类型是否有对应技能"""
        available = []
        for skill in self.list_skills():
            if not skill.enabled or not skill.loaded:
                continue
            if task_type in skill.name or task_type in skill.description:
                available.append(skill.name)
        return available

    def suggest_skills_for_task(self, task_text: str) -> List[Skill]:
        """
        根据任务文本推荐相关技能
        匹配触发关键词
        """
        suggestions = []
        task_lower = task_text.lower()

        for skill in self.list_skills():
            if not skill.enabled:
                continue
            # 关键词匹配
            match_count = sum(1 for kw in skill.trigger_keywords if kw.lower() in task_lower)
            if match_count > 0:
                suggestions.append((skill, match_count))

        # 按匹配度排序
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in suggestions]

    def add_skill(self, skill_config: Dict[str, Any]) -> bool:
        """
        添加新技能到注册表
        不创建目录，只注册
        """
        existing = [s["name"] for s in self.registry.get("skills", [])]
        if skill_config["name"] in existing:
            return False

        self.registry.setdefault("skills", []).append(skill_config)
        self._save_registry()
        return True

    def remove_skill(self, name: str) -> bool:
        """从注册表移除技能"""
        skills = self.registry.get("skills", [])
        for i, s in enumerate(skills):
            if s["name"] == name:
                del skills[i]
                self._save_registry()
                return True
        return False

    def get_all_trigger_keywords(self) -> Dict[str, List[str]]:
        """获取所有技能的触发关键词（用于快速匹配）"""
        keywords = {}
        for skill in self.list_skills():
            if skill.enabled:
                keywords[skill.name] = skill.trigger_keywords
        return keywords


if __name__ == "__main__":
    # 测试
    from pathlib import Path
    sm = SkillManager(Path("/root/.hermes/artemis/skills"))
    print("可用技能:", [s.name for s in sm.list_skills()])
    print("建议技能:", [s.name for s in sm.suggest_skills_for_task("帮我查一下这个药物的相互作用")])
