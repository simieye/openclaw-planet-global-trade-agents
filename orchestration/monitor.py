"""
Monitor 监控与告警系统
Prometheus 指标、日志聚合、健康检查、告警通知
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("openclaw.monitor")


# ============================================================
# Prometheus Metrics
# ============================================================

class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    name: str
    type: MetricType
    help: str
    labels: dict = field(default_factory=dict)
    value: float = 0.0

    def render(self) -> str:
        """渲染 Prometheus 格式"""
        label_str = ""
        if self.labels:
            label_parts = [f'{k}="{v}"' for k, v in self.labels.items()]
            label_str = "{" + ", ".join(label_parts) + "}"

        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.type.value}"]
        if self.type == MetricType.HISTOGRAM:
            lines.append(f'{self.name}_count{label_str} {self.value}')
        else:
            lines.append(f'{self.name}{label_str} {self.value}')
        return "\n".join(lines)


class MetricsRegistry:
    """Prometheus 指标注册表"""

    def __init__(self):
        self._metrics: dict[str, Metric] = {}
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._start_time = time.time()

    def register(self, name: str, metric_type: MetricType, help: str, labels: dict = None):
        self._metrics[name] = Metric(
            name=name,
            type=metric_type,
            help=help,
            labels=labels or {},
        )

    def counter_inc(self, name: str, value: float = 1.0, labels: dict = None):
        key = self._label_key(name, labels)
        self._counters[key] += value
        if name in self._metrics:
            self._metrics[name].value = self._counters[key]
            if labels:
                self._metrics[name].labels = labels

    def gauge_set(self, name: str, value: float, labels: dict = None):
        if name in self._metrics:
            self._metrics[name].value = value
            if labels:
                self._metrics[name].labels = labels

    def histogram_observe(self, name: str, value: float, labels: dict = None):
        key = self._label_key(name, labels)
        self._histograms[key].append(value)
        if name in self._metrics:
            self._metrics[name].value = sum(self._histograms[key]) / len(self._histograms[key])

    def _label_key(self, name: str, labels: dict) -> str:
        if not labels:
            return name
        label_parts = [f"{k}={v}" for k, v in sorted(labels.items())]
        return f"{name}:{','.join(label_parts)}"

    def render_all(self) -> str:
        """渲染所有指标为 Prometheus 文本格式"""
        lines = []
        for metric in self._metrics.values():
            lines.append(metric.render())
        # 添加 uptime
        uptime = time.time() - self._start_time
        lines.append(f"# HELP openclaw_uptime_seconds Engine uptime in seconds")
        lines.append(f"# TYPE openclaw_uptime_seconds gauge")
        lines.append(f"openclaw_uptime_seconds {uptime}")
        return "\n".join(lines) + "\n"

    def get_all(self) -> dict:
        """获取所有指标字典"""
        return {
            name: {"type": m.type.value, "help": m.help, "value": m.value, "labels": m.labels}
            for name, m in self._metrics.items()
        }


# ============================================================
# Alert Manager
# ============================================================

class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    id: str
    name: str
    severity: AlertSeverity
    message: str
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False
    resolved: bool = False
    metadata: dict = field(default_factory=dict)


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self._alerts: dict[str, Alert] = {}
        self._handlers: dict[str, callable] = {}
        self._alert_history: list[Alert] = []

    def register_handler(self, channel: str, handler: callable):
        """注册告警处理渠道"""
        self._handlers[channel] = handler

    async def send_alert(
        self,
        name: str,
        severity: AlertSeverity,
        message: str,
        source: str = "openclaw",
        metadata: dict = None,
        channels: list[str] = None,
    ) -> Alert:
        """发送告警"""
        alert_id = f"alert-{datetime.now().strftime('%Y%m%d%H%M%S')}-{hash(message) % 10000}"
        alert = Alert(
            id=alert_id,
            name=name,
            severity=severity,
            message=message,
            source=source,
            metadata=metadata or {},
        )
        self._alerts[alert_id] = alert
        self._alert_history.append(alert)

        logger.warning(f"[ALERT:{severity.value.upper()}] {name}: {message}")

        # 分发到各渠道
        channels = channels or list(self._handlers.keys())
        for channel in channels:
            handler = self._handlers.get(channel)
            if handler:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(alert)
                    else:
                        handler(alert)
                except Exception as e:
                    logger.error(f"Alert handler [{channel}] failed: {e}")

        return alert

    def acknowledge(self, alert_id: str):
        """确认告警"""
        alert = self._alerts.get(alert_id)
        if alert:
            alert.acknowledged = True

    def resolve(self, alert_id: str):
        """解决告警"""
        alert = self._alerts.get(alert_id)
        if alert:
            alert.resolved = True

    def get_active_alerts(self, severity: AlertSeverity = None) -> list[Alert]:
        """获取活跃告警"""
        alerts = [a for a in self._alerts.values() if not a.resolved]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def get_alert_history(self, limit: int = 100) -> list[Alert]:
        return self._alert_history[-limit:]


# ============================================================
# Health Checker
# ============================================================

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    name: str
    status: HealthStatus
    message: str = ""
    last_check: datetime = field(default_factory=datetime.now)
    latency_ms: float = 0.0


class HealthChecker:
    """健康检查器"""

    def __init__(self):
        self._checks: dict[str, callable] = {}
        self._results: dict[str, HealthCheck] = {}
        self._check_interval = 60  # 默认每60秒检查

    def register(self, name: str, check_func: callable):
        """注册健康检查"""
        self._checks[name] = check_func

    async def run_check(self, name: str) -> HealthCheck:
        """运行单个健康检查"""
        check_func = self._checks.get(name)
        if not check_func:
            return HealthCheck(name=name, status=HealthStatus.UNHEALTHY, message="Check not found")

        start = time.time()
        try:
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = check_func()
            latency = (time.time() - start) * 1000
            check = HealthCheck(
                name=name,
                status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                message="OK" if result else str(result),
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            check = HealthCheck(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency,
            )

        self._results[name] = check
        return check

    async def run_all(self) -> dict[str, HealthCheck]:
        """运行所有健康检查"""
        tasks = [self.run_check(name) for name in self._checks]
        await asyncio.gather(*tasks, return_exceptions=True)
        return self._results

    def get_overall_status(self) -> HealthStatus:
        """获取整体健康状态"""
        if not self._results:
            return HealthStatus.UNHEALTHY

        statuses = [c.status for c in self._results.values()]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        return HealthStatus.DEGRADED

    def get_results(self) -> dict:
        return {
            name: {
                "status": c.status.value,
                "message": c.message,
                "latency_ms": c.latency_ms,
                "last_check": c.last_check.isoformat(),
            }
            for name, c in self._results.items()
        }


# ============================================================
# Log Aggregator
# ============================================================

class LogAggregator:
    """日志聚合器 - 收集和分类 Agent 日志"""

    def __init__(self, max_entries: int = 10000):
        self.max_entries = max_entries
        self._logs: list[dict] = []
        self._agent_logs: dict[str, list[dict]] = defaultdict(list)
        self._error_logs: list[dict] = []
        self._taskflow_logs: dict[str, list[dict]] = defaultdict(list)

    def add_log(self, level: str, agent_id: str, message: str, metadata: dict = None):
        """添加日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "agent_id": agent_id,
            "message": message,
            "metadata": metadata or {},
        }

        self._logs.append(entry)
        self._agent_logs[agent_id].append(entry)

        if level in ("ERROR", "CRITICAL"):
            self._error_logs.append(entry)

        # 限制大小
        if len(self._logs) > self.max_entries:
            self._logs = self._logs[-self.max_entries:]

    def add_taskflow_log(self, taskflow_id: str, step: int, agent_id: str, status: str, message: str):
        """添加 TaskFlow 日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "taskflow_id": taskflow_id,
            "step": step,
            "agent_id": agent_id,
            "status": status,
            "message": message,
        }
        self._taskflow_logs[taskflow_id].append(entry)

    def get_agent_logs(self, agent_id: str, limit: int = 100) -> list[dict]:
        return self._agent_logs.get(agent_id, [])[-limit:]

    def get_taskflow_logs(self, taskflow_id: str, limit: int = 100) -> list[dict]:
        return self._taskflow_logs.get(taskflow_id, [])[-limit:]

    def get_error_logs(self, limit: int = 100) -> list[dict]:
        return self._error_logs[-limit:]

    def get_recent_logs(self, limit: int = 100) -> list[dict]:
        return self._logs[-limit:]

    def get_summary(self) -> dict:
        """获取日志摘要"""
        recent = self._logs[-1000:] if len(self._logs) > 1000 else self._logs
        levels = defaultdict(int)
        agents = defaultdict(int)
        for entry in recent:
            levels[entry["level"]] += 1
            agents[entry["agent_id"]] += 1

        return {
            "total_logs": len(self._logs),
            "error_count": len(self._error_logs),
            "recent_levels": dict(levels),
            "active_agents": len(agents),
            "top_agents": sorted(agents.items(), key=lambda x: x[1], reverse=True)[:10],
        }


# ============================================================
# Monitor Service
# ============================================================

class MonitorService:
    """监控服务 - 整合所有监控组件"""

    def __init__(self):
        self.metrics = MetricsRegistry()
        self.alerts = AlertManager()
        self.health = HealthChecker()
        self.logs = LogAggregator()
        self._running = False

        # 注册内置指标
        self._register_default_metrics()

    def _register_default_metrics(self):
        """注册默认 Prometheus 指标"""
        self.metrics.register("openclaw_agents_total", MetricType.GAUGE, "Total registered agents")
        self.metrics.register("openclaw_agents_running", MetricType.GAUGE, "Currently running agents")
        self.metrics.register("openclaw_taskflows_total", MetricType.GAUGE, "Total taskflows")
        self.metrics.register("openclaw_taskflows_completed", MetricType.COUNTER, "Completed taskflows")
        self.metrics.register("openclaw_taskflows_failed", MetricType.COUNTER, "Failed taskflows")
        self.metrics.register("openclaw_webhook_requests_total", MetricType.COUNTER, "Total webhook requests")
        self.metrics.register("openclaw_llm_calls_total", MetricType.COUNTER, "Total LLM API calls")
        self.metrics.register("openclaw_llm_tokens_total", MetricType.COUNTER, "Total LLM tokens used")
        self.metrics.register("openclaw_llm_latency_seconds", MetricType.HISTOGRAM, "LLM call latency")
        self.metrics.register("openclaw_errors_total", MetricType.COUNTER, "Total errors")
        self.metrics.register("openclaw_event_queue_size", MetricType.GAUGE, "Event queue size")

    async def start(self, check_interval: int = 60):
        """启动监控服务"""
        self._running = True
        logger.info("MonitorService started")
        while self._running:
            await asyncio.sleep(check_interval)

    async def stop(self):
        self._running = False
        logger.info("MonitorService stopped")

    def record_agent_start(self, agent_id: str):
        self.metrics.counter_inc("openclaw_agents_running")

    def record_agent_stop(self, agent_id: str):
        self.metrics.gauge_set("openclaw_agents_running", max(0, self.metrics._metrics.get("openclaw_agents_running", Metric("", MetricType.GAUGE, "")).value - 1))

    def record_taskflow_complete(self, taskflow_id: str):
        self.metrics.counter_inc("openclaw_taskflows_completed")

    def record_taskflow_fail(self, taskflow_id: str):
        self.metrics.counter_inc("openclaw_taskflows_failed")

    def record_webhook_request(self, source: str):
        self.metrics.counter_inc("openclaw_webhook_requests_total", labels={"source": source})

    def record_llm_call(self, tokens: int, latency: float):
        self.metrics.counter_inc("openclaw_llm_calls_total")
        self.metrics.counter_inc("openclaw_llm_tokens_total", value=tokens)
        self.metrics.histogram_observe("openclaw_llm_latency_seconds", latency)

    def record_error(self, error_type: str):
        self.metrics.counter_inc("openclaw_errors_total", labels={"type": error_type})

    def get_metrics_text(self) -> str:
        return self.metrics.render_all()

    def get_health_status(self) -> dict:
        return {
            "overall": self.health.get_overall_status().value,
            "checks": self.health.get_results(),
        }

    def get_log_summary(self) -> dict:
        return self.logs.get_summary()
