#!/usr/bin/env python3
"""
Artemis 自我进化 - 安全策略层
定义什么能改、什么绝对不能碰的边界
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Tuple


class EvolutionPolicy:
    """
    进化安全策略
    
    核心原则：
    1. 白名单制度：只有明确允许的文件类型才能修改
    2. 禁止危险操作：不能改认证文件、不能加 subprocess/eval
    3. 只在项目目录内：不能修改项目外部的任何文件
    4. 关键文件保护：即使在白名单内，关键文件也禁止自动改
    """
    
    # 允许修改的目录（只限这些）
    ALLOWED_DIRS = [
        "artemis",
        "skills",
        "plugins",
    ]
    
    # 允许修改的文件扩展名
    ALLOWED_EXTENSIONS = {
        ".py",    # Python 源码
        ".yaml",  # 配置文件
        ".yml",
        ".json",  # 数据文件（skills registry 等）
        ".md",    # 文档（SOUL.md 等）
        ".txt",   # 纯文本
    }
    
    # 绝对禁止修改的文件（即使扩展名允许）
    FORBIDDEN_FILES = {
        ".env", ".env.local", ".env.production",
        "config.yaml",  # 根配置
        "credentials.json", ".auth.json",
        "__init__.py",  # 包初始化（容易搞坏导入）
    }
    
    # 禁止写入的危险代码模式
    FORBIDDEN_PATTERNS = [
        (re.compile(r'os\.system\s*\('), "禁止 os.system() 调用"),
        (re.compile(r'subprocess\.(run|call|Popen|spawn)\s*\('), "禁止 subprocess 调用"),
        (re.compile(r'eval\s*\('), "禁止 eval()"),
        (re.compile(r'exec\s*\('), "禁止 exec()"),
        (re.compile(r'pickle\.load'), "禁止 pickle 反序列化"),
        (re.compile(r'__import__\s*\('), "禁止动态导入"),
        (re.compile(r'shutil\.rmtree'), "禁止删除目录"),
        (re.compile(r'os\.remove'), "禁止删除文件"),
        (re.compile(r'chmod\s*\('), "禁止修改文件权限"),
        (re.compile(r'os\.chmod'), "禁止修改文件权限"),
        (re.compile(r'Popen\s*\('), "禁止子进程"),
        (re.compile(r'multiprocessing'), "禁止多进程"),
    ]
    
    # 禁止添加的依赖（危险库）
    FORBIDDEN_PACKAGES = {
        "PyInstaller", "cx_Freeze", "nuitka",  # 打包成 exe（可疑）
        "ctypes",  # 可以修改内存
        "winreg", "ctypes"  # 系统级操作
    }
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.violations: List[Dict[str, Any]] = []
    
    def can_modify_file(self, file_path: str) -> Tuple[bool, str]:
        """
        检查文件是否允许修改
        Returns: (allowed: bool, reason: str)
        """
        path = Path(file_path).resolve()
        
        # 必须在校验目录内
        try:
            path.relative_to(self.project_root)
        except ValueError:
            return False, f"文件不在项目目录内: {path}"
        
        # 检查文件名禁止列表
        filename = path.name.lower()
        for forbidden in self.FORBIDDEN_FILES:
            if filename == forbidden.lower():
                return False, f"关键文件禁止自动修改: {filename}"
        
        # 检查目录白名单
        parts = path.relative_to(self.project_root).parts
        if len(parts) == 0:
            return False, "不能修改项目根目录本身"
        
        top_dir = parts[0]
        if top_dir not in self.ALLOWED_DIRS:
            return False, f"目录 '{top_dir}' 不在允许列表: {self.ALLOWED_DIRS}"
        
        # 检查扩展名白名单
        suffix = path.suffix.lower()
        if suffix not in self.ALLOWED_EXTENSIONS:
            return False, f"文件类型 '{suffix}' 不在允许列表"
        
        return True, "允许"
    
    def validate_python_content(self, content: str) -> List[Dict[str, Any]]:
        """
        检查 Python 代码内容是否安全
        Returns: 违规列表（空列表 = 安全）
        """
        violations = []
        
        for pattern, message in self.FORBIDDEN_PATTERNS:
            matches = pattern.findall(content)
            if matches:
                violations.append({
                    "type": "dangerous_pattern",
                    "pattern": message,
                    "matches": len(matches)
                })
        
        # 检查是否在添加危险依赖
        for pkg in self.FORBIDDEN_PACKAGES:
            if f"import {pkg}" in content or f"from {pkg}" in content:
                violations.append({
                    "type": "dangerous_package",
                    "package": pkg
                })
        
        return violations
    
    def validate_patch(self, file_path: str, old_content: str, 
                       new_content: str) -> Tuple[bool, List[str]]:
        """
        校验一个代码补丁是否安全
        
        1. 文件是否可修改
        2. 新内容是否有危险代码
        3. 改动是否太激进（整文件替换警告）
        """
        errors = []
        
        # 检查文件是否允许
        allowed, reason = self.can_modify_file(file_path)
        if not allowed:
            errors.append(f"[文件安全] {reason}")
        
        # 检查新增内容
        violations = self.validate_python_content(new_content)
        for v in violations:
            if v["type"] == "dangerous_pattern":
                errors.append(f"[代码安全] {v['pattern']} (出现{v['matches']}次)")
            elif v["type"] == "dangerous_package":
                errors.append(f"[依赖安全] 禁止引入危险包: {v['package']}")
        
        # 警告：整文件替换
        old_lines = old_content.count('\n') if old_content else 0
        new_lines = new_content.count('\n')
        if old_lines > 50 and new_lines > old_lines * 1.5:
            errors.append(f"[风险警告] 文件从 {old_lines} 行激增到 {new_lines} 行（+{new_lines-old_lines}行）")
        
        # 警告：删除了太多内容
        if old_lines > 50 and new_lines < old_lines * 0.3:
            errors.append(f"[风险警告] 文件从 {old_lines} 行缩减到 {new_lines} 行（删除了{old_lines-new_lines}行）")
        
        return len(errors) == 0, errors
    
    def get_allowed_modules(self) -> List[str]:
        """返回允许修改的模块列表"""
        modules = []
        for d in self.ALLOWED_DIRS:
            p = self.project_root / d
            if p.exists():
                for f in p.rglob("*.py"):
                    rel = f.relative_to(self.project_root)
                    modules.append(str(rel).replace("/", ".").replace(".py", ""))
        return modules
    
    def summarize(self) -> Dict[str, Any]:
        """返回策略摘要"""
        return {
            "allowed_dirs": self.ALLOWED_DIRS,
            "allowed_extensions": list(self.ALLOWED_EXTENSIONS),
            "forbidden_files": list(self.FORBIDDEN_FILES),
            "forbidden_patterns": [p[1] for p in self.FORBIDDEN_PATTERNS],
            "project_root": str(self.project_root),
        }
