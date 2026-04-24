"""
Artemis 测试套件 - 共享 fixtures
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保项目根目录可导入
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 凭证环境变量过滤 ─────────────────────────────────────────────
# 测试时清除所有凭证环境变量，防止本地密钥泄露
_CREDENTIAL_SUFFIXES = (
    "_API_KEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_CREDENTIALS",
    "_ACCESS_KEY",
    "_SECRET_ACCESS_KEY",
    "_PRIVATE_KEY",
    "_OAUTH_TOKEN",
    "_WEBHOOK_SECRET",
    "_ENCRYPT_KEY",
    "_APP_SECRET",
    "_CLIENT_SECRET",
    "_AES_KEY",
)

_CREDENTIAL_NAMES = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "ANTHROPIC_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "NOUS_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "XAI_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "MINIMAX_API_KEY",
}


@pytest.fixture
def tmp_artemis_home(tmp_path):
    """创建临时的 ~/.hermes/artemis 目录用于测试"""
    artemis_home = tmp_path / ".hermes" / "artemis"
    artemis_home.mkdir(parents=True, exist_ok=True)
    (artemis_home / "memories").mkdir(parents=True, exist_ok=True)
    (artemis_home / "logs").mkdir(parents=True, exist_ok=True)
    (artemis_home / "cache").mkdir(parents=True, exist_ok=True)
    return artemis_home


@pytest.fixture
def mock_env_vars(tmp_path, monkeypatch):
    """创建测试用的 .env 文件并设置环境变量"""
    # 创建临时 .env 文件
    env_file = tmp_path / ".env"
    env_file.write_text("""
MINIMAX_API_KEY=test_minimax_key_12345
OPENROUTER_API_KEY=test_openrouter_key_67890
ANTHROPIC_API_KEY=test_anthropic_key
DEEPSEEK_API_KEY=test_deepseek_key
GOOGLE_API_KEY=test_google_key
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
""")

    # 临时修改 LLMClient 的 env 文件路径
    import llm
    monkeypatch.setattr(llm, "load_env_file", lambda path=None: {
        "MINIMAX_API_KEY": "test_minimax_key_12345",
        "OPENROUTER_API_KEY": "test_openrouter_key_67890",
        "ANTHROPIC_API_KEY": "test_anthropic_key",
        "DEEPSEEK_API_KEY": "test_deepseek_key",
        "GOOGLE_API_KEY": "test_google_key",
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
    })

    return env_file


@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    """创建测试用的 .env 文件（用于不需要清除凭证的测试）"""
    env_file = tmp_path / ".env"
    env_file.write_text("""
MINIMAX_API_KEY=test_minimax_key_12345
OPENROUTER_API_KEY=test_openrouter_key_67890
ANTHROPIC_API_KEY=test_anthropic_key
DEEPSEEK_API_KEY=test_deepseek_key
GOOGLE_API_KEY=test_google_key
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
""")
    return env_file
