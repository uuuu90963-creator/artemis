#!/usr/bin/env python3
"""
Artemis 自我进化 - 安全代码写入层
在策略审查通过后，应用代码修改
"""

import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime


class SafeCodeWriter:
    """
    安全代码写入器
    
    功能：
    1. 备份原文件（带时间戳）
    2. 应用修改（经过策略审查）
    3. 记录变更日志
    4. 原子写入（先写.tmp再rename，防止损坏）
    """
    
    def __init__(self, project_root: Path, backup_dir: Path):
        self.project_root = Path(project_root)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.change_log: List[Dict[str, Any]] = []
    
    def apply_modification(self, file_path: str, new_content: str,
                           policy) -> Tuple[bool, str]:
        """
        应用代码修改
        
        Args:
            file_path: 相对路径（如 "artemis/router.py"）
            new_content: 新的文件内容
            policy: EvolutionPolicy 实例
        
        Returns:
            (success: bool, message: str)
        """
        full_path = self.project_root / file_path
        
        # 读取原内容（用于备份）
        if full_path.exists():
            old_content = full_path.read_text(encoding="utf-8")
        else:
            # 新文件
            old_content = ""
        
        # 策略校验
        allowed, reason = policy.can_modify_file(file_path)
        if not allowed:
            return False, f"策略拒绝: {reason}"
        
        # 内容安全校验
        violations = policy.validate_python_content(new_content)
        if violations:
            msg = "内容安全校验未通过:\n" + "\n".join(
                f"  - {v['type']}: {v.get('pattern', v.get('package', ''))}"
                for v in violations
            )
            return False, msg
        
        # 创建备份
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{full_path.stem}_{timestamp}{full_path.suffix}"
        backup_path = self.backup_dir / backup_name
        
        if old_content:
            shutil.copy2(full_path, backup_path)
        
        # 原子写入：先写 .tmp，再 rename
        tmp_path = full_path.with_suffix(full_path.suffix + ".tmp")
        try:
            tmp_path.write_text(new_content, encoding="utf-8")
            tmp_path.rename(full_path)  # 原子操作
        except Exception as e:
            # 写入失败，清理 tmp 文件
            if tmp_path.exists():
                tmp_path.unlink()
            return False, f"写入失败: {e}"
        
        # 记录变更
        self.change_log.append({
            "file": file_path,
            "timestamp": datetime.now().isoformat(),
            "backup": str(backup_path),
            "old_lines": len(old_content.splitlines()) if old_content else 0,
            "new_lines": len(new_content.splitlines()),
            "delta": len(new_content.splitlines()) - (len(old_content.splitlines()) if old_content else 0),
        })
        
        return True, f"已写入 {file_path}（备份: {backup_path.name}）"
    
    def apply_diff(self, file_path: str, diff_content: str,
                   policy) -> Tuple[bool, str]:
        """
        应用 diff 格式的修改（更精确，只改需要改的部分）
        
        diff 格式支持：
        ```diff
        @@ -10,5 +10,7 @@
         old line
        +new line added
        -line removed
        +another new line
        ```
        """
        full_path = self.project_root / file_path
        
        if not full_path.exists():
            return False, f"文件不存在（diff 模式需要原文件）: {file_path}"
        
        old_content = full_path.read_text(encoding="utf-8")
        lines = old_content.splitlines(keepends=True)
        
        # 解析 unified diff
        hunk_infos = self._parse_diff(diff_content)
        
        if not hunk_infos:
            return False, "无法解析 diff 格式"
        
        new_lines = list(lines)
        offset = 0
        for hunk in sorted(hunk_infos, key=lambda x: x['old_start']):
            old_start = hunk['old_start'] - 1 + offset  # 转 0-index
            old_count = hunk['old_count']
            new_hunk_lines = hunk['new_lines']
            
            # 应用这个 hunk
            new_lines = (
                new_lines[:old_start] +
                new_hunk_lines +
                new_lines[old_start + old_count:]
            )
            offset += len(new_hunk_lines) - old_count
        
        new_content = "".join(new_lines)
        return self.apply_modification(file_path, new_content, policy)
    
    def _parse_diff(self, diff_content: str) -> List[Dict[str, Any]]:
        """解析 unified diff 格式"""
        hunks = []
        hunk_pattern = re.compile(
            r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*?)(?=^@@|\Z)',
            re.MULTILINE | re.DOTALL
        )
        
        for match in hunk_pattern.finditer(diff_content):
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) else 1
            body = match.group(5)
            
            new_hunk_lines = []
            for line in body.splitlines():
                if line.startswith('+') and not line.startswith('+++'):
                    new_hunk_lines.append(line[1:] + '\n')
                elif line.startswith('-') or line.startswith(' '):
                    pass  # 这些是上下文或删除行
                elif not line.startswith('-'):
                    new_hunk_lines.append(line + '\n')
            
            hunks.append({
                'old_start': old_start,
                'old_count': old_count,
                'new_start': new_start,
                'new_count': new_count,
                'new_lines': new_hunk_lines
            })
        
        return hunks
    
    def get_change_summary(self) -> List[Dict[str, Any]]:
        """获取本次写入的变更摘要"""
        return self.change_log
