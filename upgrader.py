"""
Artemis 自动升级检查器

功能：
- 启动时 + 定时检查 GitHub 最新版本
- 对比当前版本，有更新时通过 Telegram 推送通知
- 支持静默升级（git pull）或手动确认后升级
- 用户配置：auto_upgrade（自动升级）、upgrade_silent（静默）
"""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  版本管理
# ═══════════════════════════════════════════════════════════════

# 当前版本（需与 install.sh 和 config.yaml 同步）
ARTEMIS_VERSION = "1.0.0"
GITHUB_REPO = "uuuu90963-creator/artemis"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
INSTALL_DIR = Path("~/.hermes/artemis").expanduser().resolve()


def get_current_version() -> str:
    """获取当前安装的版本"""
    # 优先从 VERSION 文件读取
    version_file = INSTALL_DIR / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    # 其次从 config.yaml 读取
    config_file = INSTALL_DIR / "config.yaml"
    if config_file.exists():
        try:
            with open(config_file) as f:
                cfg = yaml.safe_load(f)
                return cfg.get("version", ARTEMIS_VERSION)
        except Exception:
            pass

    return ARTEMIS_VERSION


def get_local_commits() -> Tuple[str, int]:
    """获取本地最新 commit hash 和 ahead/behind 数量"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=INSTALL_DIR,
            capture_output=True, text=True, timeout=10
        )
        commit_hash = result.stdout.strip()[:8]
        # 检查与 origin/main 的差异
        result2 = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"],
            cwd=INSTALL_DIR,
            capture_output=True, text=True, timeout=10
        )
        ahead = 0
        behind = 0
        if result2.returncode == 0:
            parts = result2.stdout.strip().split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
        return commit_hash, ahead, behind
    except Exception as e:
        logger.warning("获取 git 状态失败: %s", e)
        return "unknown", 0, 0


def parse_version(v: str) -> Tuple[int, ...]:
    """解析版本号字符串为元组，如 '1.2.3' -> (1, 2, 3)"""
    try:
        return tuple(int(p) for p in v.lstrip('v').split('.') if p.isdigit())
    except Exception:
        return (0, 0, 0)


def is_newer_version(latest: str, current: str) -> bool:
    """检查 latest 是否比 current 更新"""
    return parse_version(latest) > parse_version(current)


# ═══════════════════════════════════════════════════════════════
#  GitHub API 检查
# ═══════════════════════════════════════════════════════════════

def check_github_latest_version() -> Tuple[Optional[str], Optional[str]]:
    """
    通过 GitHub API 检查最新版本。
    
    Returns:
        (latest_version, release_url) 或 (None, error_message)
    """
    try:
        import urllib.request

        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"Artemis/{get_current_version()}",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        version = tag.lstrip('v')
        url = data.get("html_url", "")
        return version, url

    except Exception as e:
        logger.warning("检查 GitHub 版本失败: %s", e)
        return None, str(e)


# ═══════════════════════════════════════════════════════════════
#  升级执行
# ═══════════════════════════════════════════════════════════════

def do_git_pull() -> Tuple[bool, str]:
    """
    执行 git pull 升级。
    
    Returns:
        (success, message)
    """
    try:
        # 先 stash 本地修改（如果有）
        subprocess.run(["git", "stash"], cwd=INSTALL_DIR,
                       capture_output=True, timeout=30)
        # Pull
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=INSTALL_DIR,
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return True, f"升级成功！\n{result.stdout.strip()[-500:]}"
        else:
            return False, f"升级失败: {result.stderr.strip()[-200:]}"
    except Exception as e:
        return False, f"升级异常: {str(e)}"


# ═══════════════════════════════════════════════════════════════
#  升级检查器（供 cron 或启动时调用）
# ═══════════════════════════════════════════════════════════════

class UpgradeChecker:
    """
    升级检查器。
    
    工作流程：
    1. 启动时调用 check() 检查新版本
    2. 有新版本且用户开启了通知 → 返回通知消息
    3. 用户确认后调用 upgrade() 执行
    """

    STATE_FILE = Path("~/.hermes/artemis/.upgrade_state.json").expanduser()

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.auto_upgrade = self.config.get("auto_upgrade", False)
        self.silent = self.config.get("upgrade_silent", False)
        self.last_check: Optional[datetime] = None
        self.last_notified_version: Optional[str] = None
        self._load_state()

    def _load_state(self):
        """加载上次检查状态"""
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE) as f:
                    state = json.load(f)
                    self.last_check = datetime.fromisoformat(state["last_check"]) if state.get("last_check") else None
                    self.last_notified_version = state.get("last_notified_version")
            except Exception:
                pass

    def _save_state(self):
        """保存检查状态"""
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "last_check": datetime.now().isoformat(),
            "last_notified_version": self.last_notified_version,
        }
        with open(self.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def check(self, force: bool = False) -> Dict[str, Any]:
        """
        检查是否有新版本。
        
        Returns:
            {
                "has_update": bool,
                "current_version": str,
                "latest_version": str,
                "message": str,          # 通知消息
                "auto_upgraded": bool,   # 是否已自动升级
                "changelog_url": str,
            }
        """
        current = get_current_version()
        _, ahead, behind = get_local_commits()

        result = {
            "has_update": False,
            "current_version": current,
            "latest_version": current,
            "message": "",
            "auto_upgraded": False,
            "changelog_url": "",
        }

        # 检查 GitHub 最新版本
        latest_version, release_info = check_github_latest_version()

        if latest_version is None:
            # 网络错误，检查本地 git 状态作为后备
            if ahead > 0 or behind > 0:
                result["message"] = f"📊 本地版本: {current}\n本地有 {ahead}↑ {behind}↓ 未同步 commits"
                result["has_update"] = behind > 0  # behind > 0 说明远程有新提交
            return result

        result["latest_version"] = latest_version
        result["changelog_url"] = release_info if release_info.startswith("http") else ""

        # 比较版本
        if not is_newer_version(latest_version, current):
            if not force:
                return result
            result["message"] = f"✅ 当前已是最新版本: {current}"
            return result

        # 发现新版本
        result["has_update"] = True
        self.last_notified_version = latest_version
        self._save_state()

        if self.auto_upgrade and not self.silent:
            # 自动静默升级
            success, msg = do_git_pull()
            if success:
                result["message"] = f"🚀 已自动升级: {current} → {latest_version}\n{msg}"
                result["auto_upgraded"] = True
                # 写 VERSION 文件
                (INSTALL_DIR / "VERSION").write_text(latest_version)
            else:
                result["message"] = f"⚠️ 自动升级失败，请手动升级:\n{latest_version} 可用\n{message}"
            return result

        # 非自动升级：生成通知
        if self.silent:
            result["message"] = ""
            return result

        changelog = f"\n📋 更新内容: {release_info}" if release_info else ""
        auto_note = "\n🤖 开启自动升级后将在后台自动更新" if not self.auto_upgrade else ""

        result["message"] = (
            f"🚀 *Artemis 发现新版本！*\n\n"
            f"📌 当前版本: `{current}`\n"
            f"✨ 最新版本: `{latest_version}`\n"
            f"{changelog}\n\n"
            f"升级命令:\n"
            f"`cd {INSTALL_DIR} && git pull origin main`\n"
            f"{auto_note}"
        )
        return result

    def upgrade(self) -> Dict[str, Any]:
        """
        执行升级。
        
        Returns:
            {"success": bool, "message": str, "new_version": str}
        """
        latest = self.check().get("latest_version", get_current_version())
        success, msg = do_git_pull()

        if success:
            # 更新 VERSION 文件
            new_version = get_current_version()
            (INSTALL_DIR / "VERSION").write_text(new_version)
            # 重新加载依赖
            self._load_state()

        return {
            "success": success,
            "message": msg,
            "new_version": latest if success else get_current_version(),
        }


# ═══════════════════════════════════════════════════════════════
#  CLI / cron 集成
# ═══════════════════════════════════════════════════════════════

def check_upgrade_from_config() -> Dict[str, Any]:
    """从 config.yaml 读取升级配置并检查"""
    config_path = INSTALL_DIR / "config.yaml"
    config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            pass

    upgrade_cfg = config.get("upgrade", {})
    checker = UpgradeChecker({
        "auto_upgrade": upgrade_cfg.get("auto_upgrade", False),
        "silent": upgrade_cfg.get("silent", False),
    })
    return checker.check()


def register_auto_upgrade_cron(scheduler, user_id: Optional[int] = None) -> str:
    """
    向 scheduler 注册自动升级检查 cron job。
    
    Returns:
        job_id
    """
    # 检查是否已有升级 job
    for job in scheduler.list_jobs():
        if "upgrade" in job.name.lower() or "版本检查" in job.name:
            return job.job_id

    job = scheduler.create_job(
        name="Artemis 版本检查",
        prompt="VERSION_CHECK",
        schedule="0 */6 * * *",  # 每6小时检查一次
        skills=["artemis-upgrade"],
    )
    return job.job_id


# ═══════════════════════════════════════════════════════════════
#  Telegram 通知集成
# ═══════════════════════════════════════════════════════════════

def format_telegram_upgrade_message(check_result: Dict[str, Any]) -> str:
    """格式化 Telegram 升级通知消息"""
    if not check_result["has_update"]:
        return ""

    msg = check_result["message"]
    # Telegram 支持 Markdown 简化格式
    msg = msg.replace("*", "").replace("`", "'").replace("\n", "\n")
    return msg


if __name__ == "__main__":
    # CLI 方式检查
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    result = check_upgrade_from_config()
    if result["has_update"]:
        print(result["message"])
        if len(sys.argv) > 1 and sys.argv[1] == "--upgrade":
            print("\n执行升级...")
            checker = UpgradeChecker()
            r = checker.upgrade()
            print(r["message"])
    else:
        print(f"✅ 当前已是最新版本: {result['current_version']}")
