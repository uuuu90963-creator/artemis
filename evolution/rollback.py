#!/usr/bin/env python3
"""
Artemis 自我进化 - 回滚管理器
在每次进化前创建 Git snapshot，确保可以回滚
"""

import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional


class RollbackManager:
    """
    基于 Git 的回滚管理器
    
    工作方式：
    1. 每次进化前 git commit（保存当前状态）
    2. 如果测试失败，执行 git reset --hard 回滚
    3. 记录所有快照历史
    """
    
    def __init__(self, project_root: Path, snapshot_dir: Path):
        self.project_root = Path(project_root)
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots: List[Dict[str, Any]] = []
        self._load_snapshot_log()
    
    def _run_git(self, *args) -> tuple[int, str, str]:
        """运行 git 命令"""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "git 命令超时"
        except FileNotFoundError:
            return -2, "", "git 未安装"
    
    def is_git_repo(self) -> bool:
        """检查是否是 git 仓库"""
        code, _, _ = self._run_git("rev-parse", "--git-dir")
        return code == 0
    
    def init_git(self) -> bool:
        """初始化 git 仓库（如果没有）"""
        if self.is_git_repo():
            return True
        
        code, _, _ = self._run_git("init")
        if code == 0:
            # 初始 commit
            self._run_git("config", "user.email", "artemis@evolution.local")
            self._run_git("config", "user.name", "Artemis Self-Evolution")
            return True
        return False
    
    def create_snapshot(self, description: str = "") -> Optional[str]:
        """
        创建代码快照（git commit）
        
        Returns: snapshot_id (commit hash) 或 None
        """
        # 确保是 git 仓库
        if not self.is_git_repo():
            self.init_git()
        
        snapshot_id = None
        
        try:
            # 添加所有文件
            code, _, _ = self._run_git("add", "-A")
            if code != 0:
                return None
            
            # 检查是否有变更
            code, stdout, _ = self._run_git("status", "--porcelain")
            if not stdout.strip():
                # 没有变更，不需要快照
                return "no_changes"
            
            # Commit
            msg = f"[Artemis Evolution] {description or datetime.now().isoformat()}"
            code, stdout, stderr = self._run_git("commit", "-m", msg)
            
            if code == 0:
                # 获取 commit hash
                code2, hash_output, _ = self._run_git("rev-parse", "HEAD")
                snapshot_id = hash_output.strip()[:12]
                
                # 记录快照
                snapshot_record = {
                    "id": snapshot_id,
                    "description": description,
                    "timestamp": datetime.now().isoformat(),
                    "commit_msg": msg,
                }
                self.snapshots.append(snapshot_record)
                self._save_snapshot_log()
                
                return snapshot_id
            else:
                return None
        
        except Exception:
            return None
    
    def rollback_to(self, snapshot_id: str) -> Tuple[bool, str]:
        """
        回滚到指定快照
        
        Args:
            snapshot_id: git commit hash（前12位）
        
        Returns: (success, message)
        """
        if not self.is_git_repo():
            return False, "不是 git 仓库，无法回滚"
        
        code, _, stderr = self._run_git("reset", "--hard", snapshot_id)
        
        if code == 0:
            return True, f"已回滚到快照 {snapshot_id}"
        else:
            return False, f"回滚失败: {stderr}"
    
    def rollback_last(self) -> Tuple[bool, str]:
        """回滚到上一个快照（撤销最后一次进化）"""
        if not self.snapshots:
            return False, "没有可回滚的快照"
        
        last = self.snapshots[-1]
        return self.rollback_to(last["id"])
    
    def get_snapshots(self) -> List[Dict[str, Any]]:
        """获取所有快照历史"""
        return list(self.snapshots)
    
    def get_current_commit(self) -> Optional[str]:
        """获取当前 commit hash"""
        if not self.is_git_repo():
            return None
        code, output, _ = self._run_git("rev-parse", "HEAD")
        return output.strip()[:12] if code == 0 else None
    
    def _load_snapshot_log(self):
        """从文件加载快照记录"""
        log_file = self.snapshot_dir / "snapshot_log.json"
        if log_file.exists():
            import json
            try:
                data = json.loads(log_file.read_text())
                self.snapshots = data.get("snapshots", [])
            except Exception:
                pass
    
    def _save_snapshot_log(self):
        """保存快照记录到文件"""
        import json
        log_file = self.snapshot_dir / "snapshot_log.json"
        log_file.write_text(json.dumps({
            "snapshots": self.snapshots
        }, ensure_ascii=False, indent=2))
    
    def create_fallback_backup(self, changed_files: List[str]) -> Path:
        """
        创建文件级别的备份（git 不可用时的备选方案）
        把修改过的文件复制到 snapshot 目录
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = self.snapshot_dir / f"backup_{ts}"
        backup_root.mkdir(parents=True, exist_ok=True)
        
        for f in changed_files:
            src = self.project_root / f
            dst = backup_root / f
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        
        return backup_root
