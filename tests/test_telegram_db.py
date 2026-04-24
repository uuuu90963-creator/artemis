"""测试 telegram_bot.py - Telegram Bot 数据库"""

import pytest
from pathlib import Path

from telegram_bot import ConversationDB


@pytest.fixture
def conv_db(tmp_path):
    """创建临时对话数据库"""
    db_path = tmp_path / "test_conversations.db"
    db = ConversationDB(db_path)
    yield db
    # ConversationDB 使用 context manager或自动关闭，无需手动 close


class TestConversationDB:
    def test_init_creates_tables(self, conv_db):
        """初始化时创建表"""
        assert conv_db.count(123) == 0

    def test_add_message(self, conv_db):
        """添加消息"""
        conv_db.add_message(chat_id=123, role="user", content="你好")
        assert conv_db.count(123) == 1

    def test_get_history(self, conv_db):
        """获取对话历史"""
        conv_db.add_message(chat_id=123, role="user", content="你好")
        conv_db.add_message(chat_id=123, role="assistant", content="你好！")

        history = conv_db.get_history(123)
        assert len(history) == 2
        # ORDER BY timestamp DESC → 最新消息在前 (index 0)
        assert history[0]["content"] == "你好！"  # assistant (最新)
        assert history[1]["content"] == "你好"    # user (最老)

    def test_history_respects_limit(self, conv_db):
        """历史记录限制"""
        for i in range(10):
            conv_db.add_message(chat_id=123, role="user", content=f"消息{i}")

        history = conv_db.get_history(123, limit=5)
        assert len(history) == 5

    def test_clear_history(self, conv_db):
        """清空对话历史"""
        conv_db.add_message(chat_id=123, role="user", content="你好")
        conv_db.add_message(chat_id=123, role="user", content="第二句")

        conv_db.clear_history(123)
        assert conv_db.count(123) == 0

    def test_different_chats_isolated(self, conv_db):
        """不同 chat_id 隔离"""
        conv_db.add_message(chat_id=123, role="user", content="chat 123")
        conv_db.add_message(chat_id=456, role="user", content="chat 456")

        assert conv_db.count(123) == 1
        assert conv_db.count(456) == 1
        assert conv_db.count(999) == 0

    def test_message_with_image_path(self, conv_db):
        """带图片路径的消息"""
        conv_db.add_message(
            chat_id=123,
            role="user",
            content="看这个图",
            image_path="/path/to/image.png"
        )

        history = conv_db.get_history(123)
        assert history[0]["image_path"] == "/path/to/image.png"

    def test_message_with_message_id(self, conv_db):
        """带 Telegram message_id 的消息"""
        conv_db.add_message(
            chat_id=123,
            role="user",
            content="测试",
            message_id=42
        )

        # message_id 不影响查询
        history = conv_db.get_history(123)
        assert len(history) == 1

    def test_concurrent_writes(self, conv_db):
        """并发写入（WAL 模式）"""
        import threading

        def writer(chat_id, count):
            for i in range(count):
                conv_db.add_message(chat_id=chat_id, role="user", content=f"msg{i}")

        t1 = threading.Thread(target=writer, args=(123, 10))
        t2 = threading.Thread(target=writer, args=(123, 10))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # WAL 模式下应该都能写入
        assert conv_db.count(123) == 20


class TestConversationDBSchema:
    """数据库 schema 验证"""

    def test_wal_mode_enabled(self, tmp_path):
        """验证 WAL 模式已启用"""
        db_path = tmp_path / "wal_test.db"
        db = ConversationDB(db_path)

        import sqlite3
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()

        assert result.upper() == "WAL"

    def test_indexes_exist(self, tmp_path):
        """验证索引已创建"""
        db_path = tmp_path / "index_test.db"
        db = ConversationDB(db_path)

        import sqlite3
        conn = sqlite3.connect(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()

        index_names = [i[0] for i in indexes]
        assert "idx_chat_id" in index_names
        assert "idx_timestamp" in index_names
        assert "idx_chat_time" in index_names
