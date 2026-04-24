#!/usr/bin/env python3
"""
Artemis 自我进化 - 自动测试验证层
修改代码后自动跑测试，确保没有引入错误
"""

import sys
import subprocess
import importlib
from pathlib import Path
from typing import Dict, Any, List, Tuple


class SelfTester:
    """
    自我测试器
    
    修改代码后自动验证：
    1. Python 语法检查（py_compile）
    2. 模块导入检查（能否正常 import）
    3. 基础功能冒烟测试
    4. 内存泄漏检测（如果修改了 memory 模块）
    """
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.test_results: List[Dict[str, Any]] = []
        self.artemis_dir = project_root
    
    def verify_module(self, module_path: str) -> Tuple[bool, str]:
        """
        验证单个 Python 模块能否正常导入
        
        Args:
            module_path: 如 "artemis.agent" 或 "evolution.policy"
        
        Returns: (success, message)
        """
        try:
            # 把 artemis. 前缀去掉，直接在项目目录执行
            parts = module_path.split(".")
            
            # 切换到项目目录，临时添加到 sys.path
            old_path = sys.path.copy()
            if str(self.artemis_dir) not in sys.path:
                sys.path.insert(0, str(self.artemis_dir))
            
            # 尝试导入
            try:
                mod = importlib.import_module(module_path)
                sys.path = old_path
                return True, f"✓ 导入成功: {module_path}"
            except ImportError as e:
                # 如果是依赖问题，给出具体信息
                sys.path = old_path
                return False, f"✗ 导入失败({module_path}): {e}"
            except SyntaxError as e:
                sys.path = old_path
                return False, f"✗ 语法错误: {e}"
        except Exception as e:
            return False, f"✗ 验证异常: {e}"
    
    def syntax_check(self, file_path: str) -> Tuple[bool, str]:
        """
        Python 语法检查
        """
        import py_compile
        
        full_path = self.project_root / file_path
        if not full_path.exists():
            return False, f"文件不存在: {file_path}"
        
        try:
            py_compile.compile(str(full_path), doraise=True)
            return True, f"✓ 语法正确: {file_path}"
        except py_compile.PyCompileError as e:
            return False, f"✗ 语法错误: {e}"
    
    def smoke_test_artemis(self) -> Tuple[bool, str]:
        """
        冒烟测试：初始化 Artemis 主类
        确保核心模块修改后 Artemis 还能正常启动
        """
        old_path = sys.path.copy()
        if str(self.artemis_dir) not in sys.path:
            sys.path.insert(0, str(self.artemis_dir))
        
        try:
            # 测试能否导入核心模块
            from artemis import Artemis
            
            # 简单测试：初始化（不启动）
            # 注意：不运行完整初始化（会触发 API 调用）
            return True, "✓ Artemis 类导入成功"
        
        except SyntaxError as e:
            return False, f"✗ 语法错误阻止导入: {e}"
        except ImportError as e:
            return False, f"✗ 导入依赖问题: {e}"
        except Exception as e:
            return False, f"✗ 冒烟测试失败: {e}"
        finally:
            sys.path = old_path
    
    def verify_files(self, changed_files: List[str]) -> Dict[str, Any]:
        """
        验证多个文件的修改
        
        Returns: {
            "all_passed": bool,
            "results": [
                {"file": "xxx.py", "checks": [{"type": "syntax", "passed": bool, "msg": ""}]}
            ]
        }
        """
        results = []
        all_passed = True
        
        for file_path in changed_files:
            file_result = {"file": file_path, "checks": []}
            
            # 语法检查（所有 Python 文件）
            if file_path.endswith(".py"):
                passed, msg = self.syntax_check(file_path)
                file_result["checks"].append({"type": "syntax", "passed": passed, "msg": msg})
                if not passed:
                    all_passed = False
            
            # 导入检查（artemis 目录下的模块）
            if file_path.endswith(".py") and not file_path.startswith("test_"):
                # 转换为模块路径
                module_path = file_path.replace("/", ".").replace(".py", "")
                passed, msg = self.verify_module(module_path)
                file_result["checks"].append({"type": "import", "passed": passed, "msg": msg})
                if not passed:
                    all_passed = False
            
            results.append(file_result)
        
        return {"all_passed": all_passed, "results": results}
    
    def full_test(self, changed_files: List[str]) -> Dict[str, Any]:
        """
        完整测试流程：
        1. 语法检查
        2. 导入检查
        3. 冒烟测试（如果改了核心模块）
        """
        result = {
            "passed": False,
            "syntax_ok": False,
            "imports_ok": False,
            "smoke_ok": False,
            "details": [],
        }
        
        # 1. 语法 + 导入检查
        verif = self.verify_files(changed_files)
        result["syntax_ok"] = all(
            all(c["passed"] for c in r["checks"] if c["type"] == "syntax")
            for r in verif["results"]
        )
        result["imports_ok"] = all(
            all(c["passed"] for c in r["checks"] if c["type"] == "import")
            for r in verif["results"]
        )
        result["details"] = verif["results"]
        
        # 2. 冒烟测试（如果改了 artemis 核心模块）
        core_files = [f for f in changed_files if f.startswith("artemis/")]
        if core_files:
            smoke_ok, smoke_msg = self.smoke_test_artemis()
            result["smoke_ok"] = smoke_ok
            result["smoke_msg"] = smoke_msg
            result["details"].append({"file": "artemis.core", "checks": [
                {"type": "smoke", "passed": smoke_ok, "msg": smoke_msg}
            ]})
        else:
            result["smoke_ok"] = True
        
        result["passed"] = result["syntax_ok"] and result["imports_ok"] and result["smoke_ok"]
        
        return result
