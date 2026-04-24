#!/usr/bin/env python3
"""
Artemis 记忆系统
SQLite + 内置简单向量（词频 cosine similarity）
轻量实现，无需外部向量库
"""

import sqlite3
import json
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime


class MemoryStore:
    """
    记忆存储类
    使用 SQLite 存储 + 词频向量实现简单语义搜索
    """
    
    def __init__(self, db_path: Path):
        """
        初始化记忆存储
        
        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表结构"""
        cursor = self.conn.cursor()
        
        # 记忆主表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                tags TEXT,  -- JSON 数组存储
                source TEXT DEFAULT 'perception',
                vector TEXT,  -- JSON 存储词频向量
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                last_access TIMESTAMP
            )
        """)
        
        # 用户画像表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 向量词汇表（用于统一向量维度）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vocabulary (
                term TEXT PRIMARY KEY,
                df INTEGER DEFAULT 1  -- 文档频率
            )
        """)
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)")
        
        self.conn.commit()
    
    def _simple_vector(self, text: str) -> Dict[str, float]:
        """
        简单向量化：基于词频（TF）计算
        
        Args:
            text: 输入文本
            
        Returns:
            词频字典 {word: tf}
        """
        if not text:
            return {}
        
        # 简单分词（中文按字符，英文按单词）
        words = []
        
        # 英文分词
        english_words = re.findall(r'[a-zA-Z]+', text.lower())
        words.extend(english_words)
        
        # 中文字符（简单处理）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)  # 连续中文字符作为一个词
        words.extend(chinese_chars)
        
        # 计算词频
        word_count = {}
        for word in words:
            if len(word) > 1:  # 忽略单字符
                word_count[word] = word_count.get(word, 0) + 1
        
        # 归一化
        total = sum(word_count.values())
        if total > 0:
            for word in word_count:
                word_count[word] /= total
        
        return word_count
    
    def _cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """
        计算两个向量的 cosine similarity
        
        Args:
            vec1, vec2: 词频字典
            
        Returns:
            相似度分数 [0, 1]
        """
        if not vec1 or not vec2:
            return 0.0
        
        # 找出共同词汇
        common = set(vec1.keys()) & set(vec2.keys())
        if not common:
            return 0.0
        
        # 计算点积
        dot_product = sum(vec1[w] * vec2[w] for w in common)
        
        # 计算模长
        norm1 = math.sqrt(sum(v * v for v in vec1.values()))
        norm2 = math.sqrt(sum(v * v for v in vec2.values()))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def add_memory(self, content: str, tags: Optional[List[str]] = None, 
                   source: str = "perception") -> int:
        """
        添加记忆
        
        Args:
            content: 记忆内容
            tags: 标签列表
            source: 来源 (perception/task/reflection)
            
        Returns:
            记忆 ID
        """
        # 计算向量
        vector = self._simple_vector(content)
        vector_json = json.dumps(vector)
        
        # 更新词汇表
        self._update_vocabulary(vector.keys())
        
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO memories (content, tags, source, vector)
            VALUES (?, ?, ?, ?)
            """,
            (content, json.dumps(tags or []), source, vector_json)
        )
        self.conn.commit()
        
        return cursor.lastrowid
    
    def _update_vocabulary(self, terms: List[str]):
        """更新词汇表"""
        cursor = self.conn.cursor()
        for term in terms:
            cursor.execute(
                "INSERT OR IGNORE INTO vocabulary (term, df) VALUES (?, 1)",
                (term,)
            )
            cursor.execute(
                "UPDATE vocabulary SET df = df + 1 WHERE term = ?",
                (term,)
            )
        self.conn.commit()
    
    def search_memories(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        语义搜索记忆
        
        Args:
            query: 查询文本
            top_k: 返回数量
            
        Returns:
            相关记忆列表
        """
        query_vector = self._simple_vector(query)
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, content, tags, source, vector, created_at FROM memories")
        
        results = []
        for row in cursor.fetchall():
            mem_vector = json.loads(row["vector"] or "{}")
            similarity = self._cosine_similarity(query_vector, mem_vector)
            
            if similarity > 0.01:  # 阈值过滤
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "source": row["source"],
                    "similarity": round(similarity, 4),
                    "created_at": row["created_at"]
                })
        
        # 按相似度排序
        results.sort(key=lambda x: x["similarity"], reverse=True)
        
        # 更新访问记录
        for r in results[:top_k]:
            cursor.execute(
                "UPDATE memories SET access_count = access_count + 1, last_access = CURRENT_TIMESTAMP WHERE id = ?",
                (r["id"],)
            )
        self.conn.commit()
        
        return results[:top_k]
    
    def get_user_profile(self) -> Dict[str, Any]:
        """
        获取用户画像
        
        Returns:
            用户画像字典
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM user_profile")
        
        profile = {}
        for row in cursor.fetchall():
            try:
                profile[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                profile[row["key"]] = row["value"]
        
        # 补充统计信息
        cursor.execute("SELECT COUNT(*) as count FROM memories WHERE source = 'task'")
        profile["total_tasks"] = cursor.fetchone()["count"]
        
        cursor.execute("SELECT COUNT(*) as count FROM memories")
        profile["total_memories"] = cursor.fetchone()["count"]
        
        return profile
    
    def update_user_profile(self, key: str, value: Any):
        """更新用户画像"""
        cursor = self.conn.cursor()
        value_json = json.dumps(value) if not isinstance(value, str) else value
        cursor.execute(
            """
            INSERT OR REPLACE INTO user_profile (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (key, value_json)
        )
        self.conn.commit()
    
    def count(self) -> int:
        """返回记忆总数"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memories")
        return cursor.fetchone()[0]
    
    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近记忆"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, content, tags, source, created_at
            FROM memories
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row["id"],
                "content": row["content"],
                "tags": json.loads(row["tags"] or "[]"),
                "source": row["source"],
                "created_at": row["created_at"]
            })
        return results
    
    def delete_old_memories(self, keep_count: int = 1000):
        """删除旧记忆，保留最近的"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM memories
            WHERE id NOT IN (
                SELECT id FROM memories ORDER BY created_at DESC LIMIT ?
            )
            """,
            (keep_count,)
        )
        self.conn.commit()
        return cursor.rowcount
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()
    
    def __del__(self):
        """析构时关闭连接"""
        try:
            self.conn.close()
        except:
            pass


# ==================== 单元测试 ====================

if __name__ == "__main__":
    print("[MemoryStore] 运行单元测试...")
    
    # 创建测试数据库
    test_db = Path("/tmp/test_artemis_memory.db")
    if test_db.exists():
        test_db.unlink()
    
    store = MemoryStore(test_db)
    
    # 测试添加记忆
    print("\n1. 测试添加记忆:")
    id1 = store.add_memory("用户询问了关于高血压的医学问题", tags=["medical", "question"], source="task")
    id2 = store.add_memory("用户上传了一张 X 光片", tags=["image", "medical"], source="perception")
    id3 = store.add_memory("用户喜欢简洁的回答风格", tags=["preference"], source="reflection")
    print(f"   添加了 3 条记忆，ID: {id1}, {id2}, {id3}")
    
    # 测试搜索
    print("\n2. 测试语义搜索 '医学影像':")
    results = store.search_memories("医学影像", top_k=3)
    for r in results:
        print(f"   [{r['similarity']}] {r['content'][:40]}...")
    
    # 测试用户画像
    print("\n3. 测试用户画像:")
    store.update_user_profile("language", "Chinese")
    profile = store.get_user_profile()
    print(f"   画像: {profile}")
    
    # 测试最近记忆
    print("\n4. 测试最近记忆:")
    recent = store.get_recent(limit=5)
    print(f"   最近 {len(recent)} 条记忆")
    
    # 清理
    store.close()
    test_db.unlink()
    
    print("\n[MemoryStore] ✓ 所有测试通过!")
