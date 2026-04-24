"""
Artemis Cron Scheduler - 定时任务调度器
支持多种调度格式，自动投递执行结果
"""

import sqlite3
import json
import time
import threading
import re
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List


def generate_job_id() -> str:
    """生成唯一的 job_id: cron_YYYYMMDD_HHMM_xxxx"""
    now = datetime.now()
    suffix = ''.join(random.choices('abcdef0123456789', k=4))
    return f"cron_{now.strftime('%Y%m%d_%H%M')}_{suffix}"


class CronJob:
    """定时任务定义"""
    
    def __init__(self, job_id: str, prompt: str, schedule: str, name: str = "",
                 skills: List[str] = None, deliver: str = "origin",
                 model_override: str = None, script: str = None):
        self.job_id = job_id
        self.prompt = prompt
        self.schedule = schedule
        self.name = name
        self.skills = skills or []
        self.deliver = deliver
        self.model_override = model_override
        self.script = script
        self.enabled = True
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count = 0
        self.created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "job_id": self.job_id,
            "prompt": self.prompt,
            "schedule": self.schedule,
            "name": self.name,
            "skills": self.skills,
            "deliver": self.deliver,
            "model_override": self.model_override,
            "script": self.script,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_row(self) -> tuple:
        """转换为数据库行"""
        return (
            self.job_id,
            self.name,
            self.prompt,
            self.schedule,
            json.dumps(self.skills),
            self.deliver,
            self.model_override,
            self.script,
            1 if self.enabled else 0,
            self.last_run.isoformat() if self.last_run else None,
            self.next_run.isoformat() if self.next_run else None,
            self.run_count,
            self.created_at.isoformat() if self.created_at else None,
        )

    @staticmethod
    def from_row(row: tuple) -> "CronJob":
        """从数据库行创建对象"""
        job = CronJob(
            job_id=row[0],
            prompt=row[2],
            schedule=row[3],
            name=row[1] or "",
            skills=json.loads(row[4]) if row[4] else [],
            deliver=row[5] or "origin",
            model_override=row[6],
            script=row[7],
        )
        job.enabled = bool(row[8])
        job.last_run = datetime.fromisoformat(row[9]) if row[9] else None
        job.next_run = datetime.fromisoformat(row[10]) if row[10] else None
        job.run_count = row[11] or 0
        job.created_at = datetime.fromisoformat(row[12]) if row[12] else None
        return job

    def calc_next_run(self, from_time: datetime = None) -> datetime:
        """计算下次执行时间"""
        if from_time is None:
            from_time = datetime.now()
        return _calc_next_run(self.schedule, from_time)


def _parse_cron_expression(schedule: str, from_time: datetime) -> Optional[datetime]:
    """
    解析 cron 表达式 (5段式: 分 时 日 月 周)
    例如: "0 9 * * *" = 每天9点
          "30 14 * * 1-5" = 工作日下午2:30
    返回下次执行时间
    """
    parts = schedule.split()
    if len(parts) != 5:
        return None
    
    minute, hour, day, month, weekday = parts
    
    def get_next_value(pattern: str, min_val: int, max_val: int, current: int) -> Optional[int]:
        """解析 cron 字段值，计算下一个匹配的值"""
        if pattern == "*":
            return current if current >= min_val else min_val
        
        # 处理列表: "1,2,3"
        if ',' in pattern:
            values = []
            for p in pattern.split(','):
                v = get_next_value(p.strip(), min_val, max_val, current)
                if v is not None:
                    values.append(v)
            return min(values) if values else None
        
        # 处理范围: "1-5"
        if '-' in pattern:
            start, end = pattern.split('-')
            start, end = int(start), int(end)
            if current <= end:
                return max(current, start)
            return None
        
        # 处理步长: "*/5"
        if '/' in pattern:
            base, step = pattern.split('/')
            step = int(step)
            if base == "*":
                # 从 current 开始，找下一个 step 的倍数
                if current % step == 0:
                    return current
                return ((current // step) + 1) * step
            return None
        
        # 单一值
        try:
            val = int(pattern)
            if min_val <= val <= max_val:
                if val >= current:
                    return val
                # 如果当前值已过，返回 None（需要进位）
                return None
        except ValueError:
            pass
        return None
    
    # 计算下一个匹配时间
    current = from_time
    max_iterations = 366 * 24 * 60  # 最多遍历一年
    
    for _ in range(max_iterations):
        # 尝试匹配
        hour_val = get_next_value(hour, 0, 23, current.hour)
        if hour_val is None:
            # 需要进到下一天
            current = current.replace(hour=0) + timedelta(days=1)
            continue
        
        minute_val = get_next_value(minute, 0, 59, current.minute)
        if minute_val is None:
            # 需要进到下一小时
            current = current.replace(minute=0) + timedelta(hours=1)
            continue
        
        # 检查 day of month
        day_val = get_next_value(day, 1, 31, current.day)
        
        # 检查 month
        month_val = get_next_value(month, 1, 12, current.month)
        
        # 检查 day of week (0=Monday, 6=Sunday)
        weekday_val = None
        if weekday != "*":
            weekday_patterns = {
                "0": 6, "6": 0,  # Sunday
                "1": 0, "2": 1, "3": 2, "4": 3, "5": 4,
            }
            # 支持 Mon-Fri 格式
            if '-' in weekday:
                w_start, w_end = weekday.split('-')
                try:
                    w_start_n = weekday_patterns.get(w_start, int(w_start) % 7)
                    w_end_n = weekday_patterns.get(w_end, int(w_end) % 7)
                except (ValueError, KeyError):
                    w_start_n, w_end_n = None, None
                if w_start_n is not None:
                    current_weekday = current.weekday()
                    if w_start_n <= w_end_n:
                        # 正常范围 如 1-5
                        if w_start_n <= current_weekday <= w_end_n:
                            weekday_val = current_weekday
                        else:
                            # 需要跳到下周
                            days_ahead = (w_start_n - current_weekday) % 7
                            if days_ahead == 0:
                                days_ahead = 7
                            current = current.replace(hour=0, minute=0) + timedelta(days=days_ahead)
                            continue
                    else:
                        # 跨周末 如 5-1 (Fri-Mon)
                        if current_weekday >= w_start_n or current_weekday <= w_end_n:
                            weekday_val = current_weekday
                        else:
                            days_ahead = (w_start_n - current_weekday) % 7
                            current = current.replace(hour=0, minute=0) + timedelta(days=days_ahead)
                            continue
        
        # 构建目标时间
        try:
            target = current.replace(
                hour=hour_val,
                minute=minute_val,
                second=0,
                microsecond=0
            )
            # 处理 day 约束
            if day != "*":
                target = target.replace(day=day_val)
            if month != "*":
                target = target.replace(month=month_val)
            
            # 如果时间已过，跳到下一天
            if target <= from_time:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue
            
            return target
        except ValueError:
            # 日期无效（如 2月30日），跳到下一天
            current = current.replace(hour=0, minute=0) + timedelta(days=1)
            continue
    
    return None


def _calc_next_run(schedule: str, from_time: datetime) -> datetime:
    """
    解析 schedule 字符串，返回下次执行时间
    
    支持格式：
    - "30m" → from_time + 30min
    - "every 2h" → from_time + 2h
    - "every day 9:00" → 今天9点或明天9点
    - "0 9 * * *" → cron表达式
    - ISO/YYYY-MM-DD HH:MM → 具体时间点
    """
    schedule = schedule.strip()
    
    # 简单时间增量: "30m", "2h", "1h30m"
    time_match = re.match(r'^(\d+)([mhd])$', schedule, re.IGNORECASE)
    if time_match:
        value, unit = int(time_match.group(1)), time_match.group(2).lower()
        if unit == 'm':
            return from_time + timedelta(minutes=value)
        elif unit == 'h':
            return from_time + timedelta(hours=value)
        elif unit == 'd':
            return from_time + timedelta(days=value)
    
    # "every Xh" 或 "every Xm" 或 "every Xd"
    every_match = re.match(r'^every\s+(\d+)([mhd])$', schedule, re.IGNORECASE)
    if every_match:
        value, unit = int(every_match.group(1)), every_match.group(2).lower()
        if unit == 'm':
            return from_time + timedelta(minutes=value)
        elif unit == 'h':
            return from_time + timedelta(hours=value)
        elif unit == 'd':
            return from_time + timedelta(days=value)
    
    # "every day 9:00" 或 "every day at 9:00"
    day_time_match = re.match(r'^every\s+day\s+(?:at\s+)?(\d{1,2}):(\d{2})$', schedule, re.IGNORECASE)
    if day_time_match:
        hour, minute = int(day_time_match.group(1)), int(day_time_match.group(2))
        target = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= from_time:
            target += timedelta(days=1)
        return target
    
    # "every weekday 9:00"
    weekday_time_match = re.match(r'^every\s+weekday\s+(\d{1,2}):(\d{2})$', schedule, re.IGNORECASE)
    if weekday_time_match:
        hour, minute = int(weekday_time_match.group(1)), int(weekday_time_match.group(2))
        target = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= from_time:
            target += timedelta(days=1)
        # 跳过周末
        while target.weekday() >= 5:  # 5=Saturday, 6=Sunday
            target += timedelta(days=1)
        return target
    
    # ISO/YYYY-MM-DD HH:MM 格式
    iso_match = re.match(r'^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})$', schedule)
    if iso_match:
        date_str, hour, minute = iso_match.group(1), int(iso_match.group(2)), int(iso_match.group(3))
        try:
            target = datetime.strptime(f"{date_str} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
            return target
        except ValueError:
            pass
    
    # YYYY-MM-DDTHH:MM:SS (ISO format with T)
    iso_t_match = re.match(r'^(\d{4}-\d{2}-\d{2})T(\d{1,2}):(\d{2})(?::(\d{2}))?$', schedule)
    if iso_t_match:
        date_str, hour, minute = iso_t_match.group(1), int(iso_t_match.group(2)), int(iso_t_match.group(3))
        try:
            target = datetime.strptime(f"{date_str} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
            return target
        except ValueError:
            pass
    
    # Cron 表达式 (5段式)
    if re.match(r'^[\d\*\-,/]+\s+[\d\*\-,/]+\s+[\d\*\-,/]+\s+[\d\*\-,/]+\s+[\d\*\-,/]+$', schedule):
        result = _parse_cron_expression(schedule, from_time)
        if result:
            return result
    
    # 默认: 30分钟后
    return from_time + timedelta(minutes=30)


class CronScheduler:
    """定时任务调度器"""
    
    def __init__(self, agent: "Artemis", db_path: Path):
        self.agent = agent
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # 使用可重入锁
        self._runner_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._init_db()
    
    def _init_db(self):
        """创建表"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                job_id TEXT PRIMARY KEY,
                name TEXT,
                prompt TEXT,
                schedule TEXT,
                skills TEXT,
                deliver TEXT DEFAULT 'origin',
                model_override TEXT,
                script TEXT,
                enabled INTEGER DEFAULT 1,
                last_run TEXT,
                next_run TEXT,
                run_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS cron_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                started_at TEXT,
                completed_at TEXT,
                success INTEGER,
                output TEXT,
                error TEXT,
                deliver_status TEXT DEFAULT 'pending',
                FOREIGN KEY (job_id) REFERENCES cron_jobs(job_id)
            )
        """)
        conn.commit()
        conn.close()

    # ======== CRUD ========
    
    def create_job(self, prompt: str, schedule: str, name: str = "",
                   skills: List[str] = None, deliver: str = "origin",
                   model_override: str = None, script: str = None) -> CronJob:
        """创建新任务"""
        job_id = generate_job_id()
        now = datetime.now()
        
        job = CronJob(
            job_id=job_id,
            prompt=prompt,
            schedule=schedule,
            name=name,
            skills=skills or [],
            deliver=deliver,
            model_override=model_override,
            script=script,
        )
        job.enabled = True
        job.created_at = now
        job.next_run = job.calc_next_run(now)
        job.run_count = 0
        
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO cron_jobs 
                (job_id, name, prompt, schedule, skills, deliver, model_override, script, 
                 enabled, last_run, next_run, run_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, job.to_row())
            conn.commit()
            conn.close()
        
        return job

    def list_jobs(self, enabled: bool = None) -> List[CronJob]:
        """列出所有任务"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            if enabled is None:
                c.execute("SELECT * FROM cron_jobs ORDER BY created_at DESC")
            else:
                c.execute("SELECT * FROM cron_jobs WHERE enabled = ? ORDER BY created_at DESC", 
                         (1 if enabled else 0,))
            
            rows = c.fetchall()
            conn.close()
            
            return [CronJob.from_row(tuple(row)) for row in rows]

    def get_job(self, job_id: str) -> Optional[CronJob]:
        """获取指定任务"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM cron_jobs WHERE job_id = ?", (job_id,))
            row = c.fetchone()
            conn.close()
            
            if row:
                return CronJob.from_row(row)
            return None

    def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("UPDATE cron_jobs SET enabled = 0 WHERE job_id = ?", (job_id,))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("UPDATE cron_jobs SET enabled = 1 WHERE job_id = ?", (job_id,))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def remove_job(self, job_id: str) -> bool:
        """删除任务"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM cron_runs WHERE job_id = ?", (job_id,))
            c.execute("DELETE FROM cron_jobs WHERE job_id = ?", (job_id,))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def update_job(self, job_id: str, **kwargs) -> bool:
        """更新任务"""
        allowed_fields = ['name', 'prompt', 'schedule', 'skills', 'deliver', 
                         'model_override', 'script', 'enabled']
        
        updates = {}
        for key, value in kwargs.items():
            if key in allowed_fields:
                if key == 'skills':
                    updates[key] = json.dumps(value) if isinstance(value, list) else value
                elif key == 'enabled':
                    updates[key] = 1 if value else 0
                else:
                    updates[key] = value
        
        if not updates:
            return False
        
        # 如果 schedule 改变，重新计算 next_run
        if 'schedule' in updates:
            job = self.get_job(job_id)
            if job:
                updates['next_run'] = _calc_next_run(updates['schedule'], datetime.now())
        
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [job_id]
        
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(f"UPDATE cron_jobs SET {set_clause} WHERE job_id = ?", values)
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    # ======== 执行 ========
    
    def _deliver_result(self, job: CronJob, output: str, success: bool):
        """投递执行结果"""
        deliver = job.deliver or "origin"
        
        if deliver == "origin":
            # 存数据库，标记为 pending delivery
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                # 使用子查询找到最新完成的run
                c.execute("""
                    UPDATE cron_runs 
                    SET deliver_status = 'pending_delivery'
                    WHERE id = (
                        SELECT id FROM cron_runs 
                        WHERE job_id = ? AND deliver_status = 'completed'
                        ORDER BY id DESC LIMIT 1
                    )
                """, (job.job_id,))
                conn.commit()
                conn.close()
            
            # 如果有 agent，尝试发回当前对话
            if self.agent and hasattr(self.agent, 'deliver_cron_result'):
                try:
                    self.agent.deliver_cron_result(job, output, success)
                except Exception:
                    pass  # 忽略投递失败
        
        elif deliver == "local":
            # 只存数据库，不发送
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute("""
                    UPDATE cron_runs 
                    SET deliver_status = 'delivered_local'
                    WHERE id = (
                        SELECT id FROM cron_runs 
                        WHERE job_id = ? AND deliver_status = 'completed'
                        ORDER BY id DESC LIMIT 1
                    )
                """, (job.job_id,))
                conn.commit()
                conn.close()
        
        elif deliver.startswith("telegram:"):
            # 发到指定 Telegram chat
            chat_id = deliver.replace("telegram:", "").strip()
            if self.agent and hasattr(self.agent, 'telegram_bot'):
                try:
                    self.agent.telegram_bot.send_message(
                        chat_id=chat_id,
                        text=f"📋 *Cron Job: {job.name}*\n\n{output}"
                    )
                    with self._lock:
                        conn = sqlite3.connect(self.db_path)
                        c = conn.cursor()
                        c.execute("""
                            UPDATE cron_runs 
                            SET deliver_status = 'delivered_telegram'
                            WHERE id = (
                                SELECT id FROM cron_runs 
                                WHERE job_id = ? AND deliver_status = 'completed'
                                ORDER BY id DESC LIMIT 1
                            )
                        """, (job.job_id,))
                        conn.commit()
                        conn.close()
                except Exception as e:
                    pass  # 忽略发送失败
        
        elif deliver.startswith("platform:"):
            # 投放到其他平台
            platform_info = deliver.replace("platform:", "").strip()
            if self.agent and hasattr(self.agent, 'deliver_to_platform'):
                try:
                    self.agent.deliver_to_platform(platform_info, job, output, success)
                    with self._lock:
                        conn = sqlite3.connect(self.db_path)
                        c = conn.cursor()
                        c.execute("""
                            UPDATE cron_runs 
                            SET deliver_status = 'delivered_platform'
                            WHERE id = (
                                SELECT id FROM cron_runs 
                                WHERE job_id = ? AND deliver_status = 'completed'
                                ORDER BY id DESC LIMIT 1
                            )
                        """, (job.job_id,))
                        conn.commit()
                        conn.close()
                except Exception:
                    pass

    def _run_job(self, job: CronJob) -> Dict[str, Any]:
        """执行单个任务"""
        run_id = None
        started_at = datetime.now()
        result = {
            "job_id": job.job_id,
            "started_at": started_at.isoformat(),
            "success": False,
            "output": None,
            "error": None,
        }
        
        # 1. 记录开始
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO cron_runs (job_id, started_at, success, output, error, deliver_status)
                VALUES (?, ?, 0, '', '', 'running')
            """, (job.job_id, started_at.isoformat()))
            run_id = c.lastrowid
            conn.commit()
            conn.close()
        
        # 2. 执行任务
        try:
            if self.agent and hasattr(self.agent, 'run_task'):
                # 带 skills 执行
                task_output = self.agent.run_task(
                    prompt=job.prompt,
                    skills=job.skills,
                    model=job.model_override,
                    script=job.script,
                )
            elif self.agent and hasattr(self.agent, 'execute_skill'):
                # 旧版 agent 接口
                task_output = self.agent.execute_skill(
                    skill_name=job.skills[0] if job.skills else None,
                    prompt=job.prompt,
                )
            else:
                # 无 agent，仅模拟执行
                task_output = f"[Mock] Cron job executed: {job.name}\nPrompt: {job.prompt}"
            
            result["output"] = task_output
            result["success"] = True
            error = None
        except Exception as e:
            result["error"] = str(e)
            error = e
        
        completed_at = datetime.now()
        result["completed_at"] = completed_at.isoformat()
        
        # 3. 记录完成
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                UPDATE cron_runs 
                SET completed_at = ?, success = ?, output = ?, error = ?, deliver_status = 'completed'
                WHERE id = ?
            """, (completed_at.isoformat(), 1 if result["success"] else 0, 
                  result["output"] or "", result["error"] or "", run_id))
            conn.commit()
            conn.close()
        
        # 4. 投递结果
        self._deliver_result(job, result["output"] or "", result["success"])
        
        # 5. 更新任务状态
        with self._lock:
            job.last_run = started_at
            job.next_run = job.calc_next_run(started_at)
            job.run_count += 1
            self._save_job(job)
        
        return result

    def run_now(self, job_id: str) -> Dict[str, Any]:
        """立即执行某个任务"""
        job = self.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        
        return self._run_job(job)

    # ======== 调度循环 ========
    
    def _scheduler_loop(self):
        """后台调度循环"""
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    jobs = self.list_jobs(enabled=True)
                    now = datetime.now()
                    
                    for job in jobs:
                        if job.next_run and now >= job.next_run:
                            # 执行任务（在独立线程，避免阻塞）
                            threading.Thread(
                                target=self._run_job, 
                                args=(job,), 
                                daemon=True
                            ).start()
            except Exception as e:
                # 记录错误但继续运行
                pass
            
            # 每30秒检查一次
            self._stop_event.wait(30)

    def start(self):
        """启动调度器（后台线程）"""
        if self._runner_thread and self._runner_thread.is_alive():
            return  # 已启动
        
        self._stop_event.clear()
        self._runner_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._runner_thread.start()

    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        if self._runner_thread:
            self._runner_thread.join(timeout=5)

    # ======== 辅助 ========
    
    def _calc_next(self, schedule: str, from_time: datetime) -> datetime:
        """解析 schedule 字符串，返回下次执行时间"""
        return _calc_next_run(schedule, from_time)

    def _save_job(self, job: CronJob):
        """保存任务到数据库"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            UPDATE cron_jobs 
            SET name = ?, prompt = ?, schedule = ?, skills = ?, deliver = ?,
                model_override = ?, script = ?, enabled = ?, last_run = ?,
                next_run = ?, run_count = ?
            WHERE job_id = ?
        """, (
            job.name, job.prompt, job.schedule, json.dumps(job.skills),
            job.deliver, job.model_override, job.script,
            1 if job.enabled else 0,
            job.last_run.isoformat() if job.last_run else None,
            job.next_run.isoformat() if job.next_run else None,
            job.run_count, job.job_id
        ))
        conn.commit()
        conn.close()

    def get_next_runs(self, top_k: int = 5) -> List[Dict]:
        """获取即将执行的任务"""
        with self._lock:
            jobs = self.list_jobs(enabled=True)
            
        upcoming = []
        for job in jobs:
            if job.next_run:
                upcoming.append({
                    "job_id": job.job_id,
                    "name": job.name,
                    "next_run": job.next_run.isoformat(),
                    "schedule": job.schedule,
                })
        
        # 按时间排序
        upcoming.sort(key=lambda x: x["next_run"])
        return upcoming[:top_k]

    def get_run_history(self, job_id: str = None, limit: int = 20) -> List[Dict]:
        """获取执行历史"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            if job_id:
                c.execute("""
                    SELECT * FROM cron_runs 
                    WHERE job_id = ? 
                    ORDER BY started_at DESC 
                    LIMIT ?
                """, (job_id, limit))
            else:
                c.execute("""
                    SELECT * FROM cron_runs 
                    ORDER BY started_at DESC 
                    LIMIT ?
                """, (limit,))
            
            rows = c.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def get_pending_deliveries(self) -> List[Dict]:
        """获取待投递的结果"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT r.*, j.name as job_name, j.deliver
                FROM cron_runs r
                JOIN cron_jobs j ON r.job_id = j.job_id
                WHERE r.deliver_status = 'pending_delivery'
                ORDER BY r.started_at DESC
            """)
            rows = c.fetchall()
            conn.close()
            return [dict(row) for row in rows]
    
    def mark_delivered(self, run_id: int):
        """标记为已投递"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                UPDATE cron_runs SET deliver_status = 'delivered_origin' WHERE id = ?
            """, (run_id,))
            conn.commit()
            conn.close()


# ======== 测试代码 ========
if __name__ == "__main__":
    from pathlib import Path
    
    print("=== Cron Scheduler 测试 ===\n")
    
    # 创建测试数据库
    test_db = Path("/tmp/test_cron.db")
    if test_db.exists():
        test_db.unlink()
    
    scheduler = CronScheduler(None, test_db)
    
    # 测试 schedule 解析
    now = datetime.now()
    print(f"当前时间: {now}\n")
    
    test_schedules = [
        "30m",
        "2h", 
        "1d",
        "every 2h",
        "every 30m",
        "every day 9:00",
        "every day 14:30",
        "0 9 * * *",  # 每天9点
        "30 14 * * 1-5",  # 工作日下午2:30
    ]
    
    print("Schedule 解析测试:")
    print("-" * 50)
    for sched in test_schedules:
        try:
            next_time = scheduler._calc_next(sched, now)
            print(f"  {sched:20} → {next_time}")
        except Exception as e:
            print(f"  {sched:20} → ERROR: {e}")
    
    print("\n" + "-" * 50)
    
    # 测试创建任务
    print("\n创建测试任务:")
    job1 = scheduler.create_job(
        prompt="总结今天的天气",
        schedule="30m",
        name="天气总结",
        skills=["weather"],
        deliver="origin"
    )
    print(f"  创建任务1: {job1.job_id}")
    print(f"  下次执行: {job1.next_run}")
    
    job2 = scheduler.create_job(
        prompt="检查系统状态",
        schedule="every 2h",
        name="系统检查",
        skills=["system"],
        deliver="local"
    )
    print(f"  创建任务2: {job2.job_id}")
    
    job3 = scheduler.create_job(
        prompt="发送早安消息",
        schedule="0 9 * * *",
        name="早安提醒",
        skills=[],
        deliver="telegram:123456789"
    )
    print(f"  创建任务3: {job3.job_id}")
    
    # 列出所有任务
    print("\n所有任务:")
    for job in scheduler.list_jobs():
        print(f"  [{job.job_id}] {job.name}")
        print(f"    schedule: {job.schedule}, deliver: {job.deliver}")
        print(f"    next_run: {job.next_run}, enabled: {job.enabled}")
        print()
    
    # 获取即将执行的任务
    print("即将执行的任务 (top 3):")
    for item in scheduler.get_next_runs(3):
        print(f"  {item['name']}: {item['next_run']}")
    
    # 测试立即运行
    print("\n立即执行任务测试:")
    result = scheduler.run_now(job1.job_id)
    print(f"  执行结果: success={result['success']}")
    if result.get('output'):
        print(f"  输出: {result['output'][:100]}...")
    
    # 获取执行历史
    print("\n执行历史:")
    for run in scheduler.get_run_history(limit=5):
        print(f"  [{run['job_id']}] success={run['success']}, at={run['started_at']}")
    
    # 清理
    scheduler.stop()
    print("\n测试完成!")
