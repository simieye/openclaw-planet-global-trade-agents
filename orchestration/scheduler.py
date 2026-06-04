"""
Cron Scheduler 定时调度器
基于 cron 表达式的定时任务调度，驱动 Agent 和 TaskFlow 定时执行
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("openclaw.scheduler")


# ============================================================
# Cron Expression Parser
# ============================================================

class CronField(Enum):
    MINUTE = 0
    HOUR = 1
    DAY_OF_MONTH = 2
    MONTH = 3
    DAY_OF_WEEK = 4


@dataclass
class CronSchedule:
    """Cron 表达式解析结果"""
    minutes: set[int]
    hours: set[int]
    days_of_month: set[int]
    months: set[int]
    days_of_week: set[int]
    raw: str

    @classmethod
    def parse(cls, expr: str) -> "CronSchedule":
        """解析 cron 表达式 (5字段: minute hour dom month dow)"""
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {expr} (need 5 fields)")

        return cls(
            minutes=cls._parse_field(parts[0], 0, 59),
            hours=cls._parse_field(parts[1], 0, 23),
            days_of_month=cls._parse_field(parts[2], 1, 31),
            months=cls._parse_field(parts[3], 1, 12),
            days_of_week=cls._parse_field(parts[4], 0, 6),
            raw=expr,
        )

    @staticmethod
    def _parse_field(field: str, min_val: int, max_val: int) -> set[int]:
        """解析单个 cron 字段"""
        values = set()

        if field == "*":
            return set(range(min_val, max_val + 1))

        for part in field.split(","):
            part = part.strip()

            # 步长: */5 或 1-30/5
            if "/" in part:
                range_part, step = part.split("/")
                step = int(step)
                if range_part == "*":
                    start, end = min_val, max_val
                elif "-" in range_part:
                    start, end = map(int, range_part.split("-"))
                else:
                    start = int(range_part)
                    end = max_val
                values.update(range(start, end + 1, step))
            # 范围: 1-5
            elif "-" in part:
                start, end = map(int, part.split("-"))
                values.update(range(start, end + 1))
            else:
                values.add(int(part))

        return values

    def matches(self, dt: datetime) -> bool:
        """检查给定时间是否匹配"""
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.day in self.days_of_month
            and dt.month in self.months
            and dt.weekday() in self.days_of_week
        )

    def next_run(self, from_time: datetime = None) -> datetime:
        """计算下次执行时间"""
        if from_time is None:
            from_time = datetime.now()
        current = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # 最多搜索 2 年
        max_iterations = 365 * 24 * 60 * 2
        for _ in range(max_iterations):
            if self.matches(current):
                return current
            current += timedelta(minutes=1)

        raise ValueError(f"Cannot find next run for: {self.raw}")


# ============================================================
# Scheduled Task
# ============================================================

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScheduledTask:
    """定时任务"""
    id: str
    name: str
    description: str
    cron: CronSchedule
    handler: Callable
    handler_args: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    enabled: bool = True

    def __post_init__(self):
        self.next_run = self.cron.next_run()


# ============================================================
# Cron Scheduler
# ============================================================

class CronScheduler:
    """Cron 定时调度器"""

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._check_interval = 30  # 每30秒检查一次

    def add_task(
        self,
        task_id: str,
        name: str,
        cron_expr: str,
        handler: Callable,
        description: str = "",
        handler_args: dict = None,
    ) -> ScheduledTask:
        """添加定时任务"""
        schedule = CronSchedule.parse(cron_expr)
        task = ScheduledTask(
            id=task_id,
            name=name,
            description=description,
            cron=schedule,
            handler=handler,
            handler_args=handler_args or {},
        )
        self._tasks[task_id] = task
        logger.info(f"Scheduled task: {task_id} ({name}) cron='{cron_expr}' next={task.next_run}")
        return task

    def remove_task(self, task_id: str):
        """移除任务"""
        self._tasks.pop(task_id, None)

    def enable_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if task:
            task.enabled = True

    def disable_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if task:
            task.enabled = False

    async def start(self):
        """启动调度器"""
        self._running = True
        logger.info(f"CronScheduler started with {len(self._tasks)} tasks")
        while self._running:
            await self._check_and_execute()
            await asyncio.sleep(self._check_interval)

    async def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("CronScheduler stopped")

    async def _check_and_execute(self):
        """检查并执行到期任务"""
        now = datetime.now()
        tasks_to_run = []

        for task in self._tasks.values():
            if not task.enabled:
                continue
            if task.next_run and now >= task.next_run:
                tasks_to_run.append(task)

        for task in tasks_to_run:
            asyncio.create_task(self._execute_task(task))

    async def _execute_task(self, task: ScheduledTask):
        """执行单个任务"""
        task.status = TaskStatus.RUNNING
        task.last_run = datetime.now()
        logger.info(f"[Scheduler] Running task: {task.id} ({task.name})")

        try:
            if asyncio.iscoroutinefunction(task.handler):
                await task.handler(**task.handler_args)
            else:
                task.handler(**task.handler_args)

            task.status = TaskStatus.COMPLETED
            task.run_count += 1
            logger.info(f"[Scheduler] Completed task: {task.id} (run #{task.run_count})")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_count += 1
            task.last_error = str(e)
            logger.error(f"[Scheduler] Failed task: {task.id} - {e}")

        finally:
            # 计算下次执行时间
            task.next_run = task.cron.next_run(datetime.now())

    def get_status(self) -> dict:
        """获取调度器状态"""
        return {
            "running": self._running,
            "total_tasks": len(self._tasks),
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "cron": t.cron.raw,
                    "status": t.status.value,
                    "last_run": t.last_run.isoformat() if t.last_run else None,
                    "next_run": t.next_run.isoformat() if t.next_run else None,
                    "run_count": t.run_count,
                    "error_count": t.error_count,
                    "enabled": t.enabled,
                }
                for t in self._tasks.values()
            ],
        }


# ============================================================
# Agent Schedule Loader
# ============================================================

class AgentScheduleLoader:
    """从 Agent 配置加载定时任务"""

    def __init__(self, scheduler: CronScheduler, runtime):
        self.scheduler = scheduler
        self.runtime = runtime

    def load_from_agent(self, agent_config: dict):
        """从 Agent 配置加载定时任务"""
        agent_id = agent_config.get("agent", {}).get("id", "")
        schedule_tasks = agent_config.get("agent", {}).get("schedule", {}).get("tasks", [])

        for task in schedule_tasks:
            task_id = f"{agent_id}.{task['name']}"

            async def handler(aid=agent_id, tname=task["name"], tdesc=task.get("description", "")):
                await self.runtime.execute_agent(
                    agent_id=aid,
                    action=tname,
                    input_data={"trigger": "scheduled", "description": tdesc},
                )

            self.scheduler.add_task(
                task_id=task_id,
                name=f"{agent_id}:{task['name']}",
                cron_expr=task["cron"],
                handler=handler,
                description=task.get("description", ""),
            )
            logger.info(f"Loaded schedule: {task_id} cron='{task['cron']}'")
