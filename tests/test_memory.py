"""测试 memory.py - 记忆系统"""

import pytest
from pathlib import Path

from memory import MemoryStore


@pytest.fixture
def mem_db(tmp_path):
    """创建临时记忆数据库"""
    db_path = tmp_path / "test_memory.db"
    m = MemoryStore(db_path)
    yield m
    m.close()


class TestMemoryStore:
    def test_init_creates_tables(self, mem_db):
        """验证初始化时创建了必要的表"""
        assert mem_db.count() == 0

    def test_add_and_search_memory(self, mem_db):
        """添加记忆并搜索"""
        mem_db.add_memory("今天看了CT片子", tags=["医学", "影像"])
        assert mem_db.count() == 1

        results = mem_db.search_memories("CT")
        assert len(results) >= 1

    def test_add_memory_with_source(self, mem_db):
        """添加带来源的记忆"""
        mem_db.add_memory("用户喜欢简洁的回答", source="preference")
        assert mem_db.count() == 1

    def test_get_recent_memories(self, mem_db):
        """获取最近的记忆"""
        for i in range(5):
            mem_db.add_memory(f"记忆{i}", tags=[f"tag{i}"])

        recent = mem_db.get_recent(3)
        assert len(recent) == 3

    def test_user_profile(self, mem_db):
        """用户画像存取"""
        mem_db.update_user_profile("name", "小明")
        profile = mem_db.get_user_profile()
        assert profile.get("name") == "小明"

    def test_delete_old_memories(self, mem_db):
        """删除旧记忆"""
        for i in range(10):
            mem_db.add_memory(f"旧记忆{i}", tags=["old"])

        mem_db.delete_old_memories(keep_count=5)
        assert mem_db.count() <= 5

    def test_vector_search(self, mem_db):
        """向量搜索（英文词匹配）"""
        mem_db.add_memory("Python is a great programming language", tags=["编程"])
        mem_db.add_memory("JavaScript is used for web development", tags=["编程"])
        mem_db.add_memory("The weather is nice today", tags=["日常"])

        results = mem_db.search_memories("Python programming")
        assert len(results) >= 1  # 至少匹配 Python
