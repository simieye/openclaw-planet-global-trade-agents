"""
OpenClaw 智能体集群调度引擎
统一调度入口，管理所有 Agent 生命周期、TaskFlow 执行、Webhook 事件分发
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# TOML 加载器：优先使用 tomli（更宽松），回退到 tomllib
try:
    import tomllib as _toml_lib
    _toml_loads = _toml_lib.loads
except ImportError:
    try:
        import tomli as _toml_lib
        _toml_loads = _toml_lib.loads
    except ImportError:
        import tomllib as _toml_lib
        _toml_loads = _toml_lib.loads


def _load_toml(path: str) -> dict:
    """加载 TOML 文件，自动处理编码和内联表兼容问题"""
    with open(path, "rb") as f:
        raw_bytes = f.read()

    # Python 3.11+ 的 tomllib.loads 需要 str；tomli 也接受 str
    try:
        return _toml_loads(raw_bytes.decode("utf-8"))
    except (TypeError, Exception):
        try:
            return _toml_loads(raw_bytes)
        except Exception:
            try:
                import tomli
                return tomli.loads(raw_bytes.decode("utf-8"))
            except ImportError:
                raise ImportError(
                    "Failed to parse TOML. Install tomli: pip install tomli"
                )

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("openclaw.engine")


# ============================================================
# 核心数据结构
# ============================================================
class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    PAUSED = "paused"


class TaskFlowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class AgentConfig:
    """智能体配置"""
    id: str
    name: str
    layer: str
    description: str
    config_path: str
    priority: int
    triggers: list[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    last_run: Optional[datetime] = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskFlowStep:
    """TaskFlow步骤"""
    order: int
    agent_id: str
    action: str
    input_from: str
    output_to: str
    timeout_seconds: int = 300
    condition: Optional[str] = None


@dataclass
class TaskFlowConfig:
    """TaskFlow配置"""
    id: str
    name: str
    description: str
    priority: str
    trigger: str
    steps: list[TaskFlowStep] = field(default_factory=list)
    status: TaskFlowStatus = TaskFlowStatus.PENDING


@dataclass
class WebhookRoute:
    """Webhook路由"""
    path: str
    source: str
    description: str
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Event:
    """事件"""
    id: str
    source: str
    name: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================
# 配置加载器
# ============================================================
class ConfigLoader:
    """TOML配置文件加载器"""

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def load_toml(self, path: str) -> dict[str, Any]:
        """加载TOML文件"""
        full_path = self.base_path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Config file not found: {full_path}")
        return _load_toml(str(full_path))

    def load_cluster_config(self) -> dict[str, Any]:
        """加载集群配置"""
        return self.load_toml("deploy/cluster.toml")

    def load_agent_registry(self) -> dict[str, Any]:
        """加载Agent注册表"""
        return self.load_toml("agents/registry.toml")

    def load_agent_config(self, config_path: str) -> dict[str, Any]:
        """加载单个Agent配置"""
        return self.load_toml(config_path)

    def load_taskflows(self) -> dict[str, Any]:
        """加载TaskFlow配置"""
        return self.load_toml("taskflows/taskflows.toml")

    def load_webhooks(self) -> dict[str, Any]:
        """加载Webhook配置"""
        return self.load_toml("webhooks/gateway.toml")

    def load_knowledge_base(self) -> dict[str, Any]:
        """加载知识库配置"""
        return self.load_toml("knowledge/base.toml")


# ============================================================
# Agent 注册中心
# ============================================================
class AgentRegistry:
    """智能体注册中心 - 管理所有Agent实例"""

    def __init__(self, loader: ConfigLoader):
        self.loader = loader
        self.agents: dict[str, AgentConfig] = {}
        self._loaded = False

    def load_all(self):
        """加载所有Agent"""
        if self._loaded:
            return

        registry_data = self.loader.load_agent_registry()
        for agent_entry in registry_data.get("agents", []):
            try:
                agent_config = self.loader.load_agent_config(agent_entry["config"])
                agent = AgentConfig(
                    id=agent_entry["id"],
                    name=agent_entry["name"],
                    layer=agent_entry["layer"],
                    description=agent_entry["description"],
                    config_path=agent_entry["config"],
                    priority=agent_entry["priority"],
                    triggers=agent_entry.get("triggers", []),
                    config=agent_config,
                )
                self.agents[agent.id] = agent
                logger.info(f"Registered agent: {agent.id} ({agent.name})")
            except Exception as e:
                logger.error(f"Failed to load agent {agent_entry['id']}: {e}")

        self._loaded = True
        logger.info(f"Agent registry loaded: {len(self.agents)} agents registered")

    def get(self, agent_id: str) -> Optional[AgentConfig]:
        """获取Agent"""
        return self.agents.get(agent_id)

    def get_by_layer(self, layer: str) -> list[AgentConfig]:
        """按层级获取Agent"""
        return [a for a in self.agents.values() if a.layer == layer]

    def get_by_trigger(self, trigger: str) -> list[AgentConfig]:
        """按触发器获取Agent"""
        return [a for a in self.agents.values() if trigger in a.triggers]

    def list_all(self) -> list[AgentConfig]:
        """列出所有Agent"""
        return list(self.agents.values())


# ============================================================
# TaskFlow 执行引擎
# ============================================================
class TaskFlowEngine:
    """TaskFlow执行引擎 - 管理流水线执行"""

    def __init__(self, loader: ConfigLoader, registry: AgentRegistry):
        self.loader = loader
        self.registry = registry
        self.taskflows: dict[str, TaskFlowConfig] = {}
        self.active_runs: dict[str, TaskFlowConfig] = {}
        self._loaded = False

    def load_all(self):
        """加载所有TaskFlow"""
        if self._loaded:
            return

        tf_data = self.loader.load_taskflows()

        # 兼容两种 TOML 解析结构：
        # 1. tomllib: {"taskflow.customer_acquisition": {...}}  (dotted keys)
        # 2. tomli:   {"taskflow": {"customer_acquisition": {...}}}  (nested tables)
        taskflows_raw = tf_data.get("taskflow", {})
        if not taskflows_raw:
            # 回退：可能是 dotted key 格式
            taskflows_raw = {k: v for k, v in tf_data.items() if k != "meta"}

        for tf_id, tf_entry in taskflows_raw.items():
            # 跳过 error_handling 和 notifications 等配置项
            if tf_id in ("error_handling", "notifications"):
                continue
            # 跳过字符串值
            if not isinstance(tf_entry, dict):
                continue

            steps = []
            for step_entry in tf_entry.get("steps", []):
                step = TaskFlowStep(
                    order=step_entry["order"],
                    agent_id=step_entry["agent"],
                    action=step_entry["action"],
                    input_from=step_entry["input_from"],
                    output_to=step_entry["output_to"],
                    timeout_seconds=step_entry.get("timeout_seconds", 300),
                    condition=step_entry.get("condition"),
                )
                steps.append(step)

            tf_config = TaskFlowConfig(
                id=tf_id,
                name=tf_entry["name"],
                description=tf_entry["description"],
                priority=tf_entry["priority"],
                trigger=tf_entry["trigger"],
                steps=steps,
            )
            self.taskflows[tf_id] = tf_config
            logger.info(f"Loaded TaskFlow: {tf_id} ({tf_config.name}) with {len(steps)} steps")

        self._loaded = True
        logger.info(f"TaskFlow engine loaded: {len(self.taskflows)} taskflows")

    async def execute(self, tf_id: str, input_data: dict[str, Any] = None) -> dict[str, Any]:
        """执行TaskFlow"""
        tf = self.taskflows.get(tf_id)
        if not tf:
            raise ValueError(f"TaskFlow not found: {tf_id}")

        logger.info(f"Starting TaskFlow: {tf_id} ({tf.name})")
        tf.status = TaskFlowStatus.RUNNING
        results = {}

        for step in sorted(tf.steps, key=lambda s: s.order):
            logger.info(f"  Step {step.order}: {step.agent_id} -> {step.action}")

            # 检查条件
            if step.condition:
                condition_met = self._evaluate_condition(step.condition, results)
                if not condition_met:
                    logger.info(f"    Condition not met, skipping: {step.condition}")
                    continue

            # 获取Agent
            agent = self.registry.get(step.agent_id)
            if not agent:
                logger.error(f"    Agent not found: {step.agent_id}")
                tf.status = TaskFlowStatus.FAILED
                break

            # 模拟Agent执行（实际生产环境会调用OpenClaw Agent API）
            try:
                step_result = await self._execute_agent_step(agent, step, input_data)
                results[step.agent_id] = step_result
                logger.info(f"    Completed: {step.agent_id}")
            except Exception as e:
                logger.error(f"    Failed: {step.agent_id} - {e}")
                tf.status = TaskFlowStatus.FAILED
                break
        else:
            tf.status = TaskFlowStatus.COMPLETED
            logger.info(f"TaskFlow completed: {tf_id}")

        return results

    def _evaluate_condition(self, condition: str, results: dict) -> bool:
        """评估条件表达式"""
        # 简化实现，实际应使用安全的表达式求值
        try:
            # 解析 condition like "lead_score >= 70"
            parts = condition.split()
            if len(parts) >= 3:
                var_name, op, value = parts[0], parts[1], parts[2]
                # 从results中查找变量
                actual_value = self._resolve_variable(var_name, results)
                if actual_value is not None:
                    if op == ">=":
                        return float(actual_value) >= float(value)
                    elif op == "<=":
                        return float(actual_value) <= float(value)
                    elif op == ">":
                        return float(actual_value) > float(value)
                    elif op == "<":
                        return float(actual_value) < float(value)
                    elif op == "==":
                        return str(actual_value) == str(value)
                    elif op == "!=":
                        return str(actual_value) != str(value)
            return True  # 默认通过
        except Exception:
            return True

    def _resolve_variable(self, var_name: str, results: dict) -> Any:
        """从结果中解析变量"""
        # 简化实现
        return results.get(var_name, {}).get(var_name, None)

    async def _execute_agent_step(self, agent: AgentConfig, step: TaskFlowStep, input_data: dict = None) -> dict[str, Any]:
        """执行Agent步骤（模拟）"""
        # 实际生产环境会调用 OpenClaw Agent Runtime API
        await asyncio.sleep(0.5)  # 模拟执行时间
        return {
            "agent_id": agent.id,
            "action": step.action,
            "status": "completed",
            "result": f"Agent {agent.id} executed {step.action} successfully",
            "timestamp": datetime.now().isoformat(),
        }

    def get_by_trigger(self, trigger: str) -> list[TaskFlowConfig]:
        """按触发器获取TaskFlow"""
        return [tf for tf in self.taskflows.values() if trigger in tf.trigger]


# ============================================================
# Webhook Gateway
# ============================================================
class WebhookGateway:
    """Webhook网关 - 事件路由与分发"""

    def __init__(self, loader: ConfigLoader, taskflow_engine: TaskFlowEngine, registry: AgentRegistry):
        self.loader = loader
        self.taskflow_engine = taskflow_engine
        self.registry = registry
        self.routes: list[WebhookRoute] = []
        self.event_handlers: dict[str, callable] = {}
        self._loaded = False

    def load_all(self):
        """加载Webhook路由"""
        if self._loaded:
            return

        wh_data = self.loader.load_webhooks()
        # 兼容两种 TOML 解析结构
        gateway_data = wh_data.get("gateway", wh_data)
        for route_entry in gateway_data.get("routes", []):
            route = WebhookRoute(
                path=route_entry["path"],
                source=route_entry["source"],
                description=route_entry["description"],
                events=route_entry.get("events", []),
            )
            self.routes.append(route)
            logger.info(f"Registered webhook route: {route.path} ({route.source})")

        self._loaded = True
        logger.info(f"Webhook gateway loaded: {len(self.routes)} routes")

    def register_handler(self, event_name: str, handler: callable):
        """注册事件处理器"""
        self.event_handlers[event_name] = handler

    async def handle_event(self, event: Event) -> dict[str, Any]:
        """处理事件"""
        logger.info(f"Handling event: {event.source}/{event.name}")

        # 查找匹配的路由
        for route in self.routes:
            for evt in route.events:
                if evt["name"] == event.name:
                    action = evt["action"]
                    target = evt["target"]

                    if action == "trigger_agent":
                        return await self._trigger_agent(target, evt, event)
                    elif action == "trigger_taskflow":
                        return await self._trigger_taskflow(target, evt, event)
                    elif action == "continue_taskflow":
                        return await self._continue_taskflow(event)
                    elif action == "notify_ceo":
                        return await self._notify_ceo(event)

        logger.warning(f"No handler found for event: {event.source}/{event.name}")
        return {"status": "unhandled", "event": event.name}

    async def _trigger_agent(self, agent_id: str, evt_config: dict, event: Event) -> dict:
        """触发Agent"""
        agent = self.registry.get(agent_id)
        if agent:
            logger.info(f"Triggering agent: {agent_id} for event {event.name}")
            agent.status = AgentStatus.RUNNING
            # 实际生产环境调用OpenClaw Agent API
            return {"status": "triggered", "agent": agent_id, "action": evt_config.get("payload", {}).get("action")}
        return {"status": "agent_not_found", "agent": agent_id}

    async def _trigger_taskflow(self, tf_id: str, evt_config: dict, event: Event) -> dict:
        """触发TaskFlow"""
        if tf_id in self.taskflow_engine.taskflows:
            logger.info(f"Triggering TaskFlow: {tf_id} for event {event.name}")
            return await self.taskflow_engine.execute(tf_id, event.data)
        return {"status": "taskflow_not_found", "taskflow": tf_id}

    async def _continue_taskflow(self, event: Event) -> dict:
        """继续TaskFlow"""
        return {"status": "continued", "task_id": event.data.get("task_id")}

    async def _notify_ceo(self, event: Event) -> dict:
        """通知CEO Agent"""
        logger.info(f"Notifying CEO Agent: {event.data}")
        return {"status": "notified", "agent": "ceo_agent"}


# ============================================================
# 调度引擎主类
# ============================================================
class OrchestrationEngine:
    """OpenClaw 统一调度引擎 - 集成所有子系统"""

    def __init__(self, base_path: str = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)

        # 核心组件
        self.loader = ConfigLoader(self.base_path)
        self.registry = AgentRegistry(self.loader)
        self.taskflow_engine = TaskFlowEngine(self.loader, self.registry)
        self.webhook_gateway = WebhookGateway(self.loader, self.taskflow_engine, self.registry)

        # Agent Runtime（延迟导入避免循环依赖）
        self._runtime = None
        self._scheduler = None

        # 状态
        self.running = False
        self._tasks: list[asyncio.Task] = []

    @property
    def runtime(self):
        """懒加载 AgentRuntime"""
        if self._runtime is None:
            try:
                from .runtime import AgentRuntime
            except ImportError:
                from orchestration.runtime import AgentRuntime
            self._runtime = AgentRuntime(self.base_path)
        return self._runtime

    @property
    def scheduler(self):
        """懒加载 CronScheduler"""
        if self._scheduler is None:
            try:
                from .scheduler import CronScheduler, AgentScheduleLoader
            except ImportError:
                from orchestration.scheduler import CronScheduler, AgentScheduleLoader
            self._scheduler = CronScheduler()
        return self._scheduler

    def initialize(self, with_runtime: bool = True, with_scheduler: bool = True):
        """初始化所有组件"""
        logger.info("=" * 60)
        logger.info("OpenClaw 跨境电商智能体集群调度引擎")
        logger.info("=" * 60)

        # 加载集群配置
        cluster_config = self.loader.load_cluster_config()
        self.cluster_config = cluster_config
        logger.info(f"Cluster: {cluster_config['cluster']['name']} v{cluster_config['cluster']['version']}")

        # 加载Agent注册表
        self.registry.load_all()

        # 加载TaskFlow
        self.taskflow_engine.load_all()

        # 加载Webhook
        self.webhook_gateway.load_all()

        # 加载知识库配置
        kb_config = self.loader.load_knowledge_base()
        logger.info(f"Knowledge base: {kb_config['knowledge_base']['name']}")

        # 初始化 Agent Runtime
        if with_runtime:
            try:
                self.runtime.load_all_agents()
                logger.info(f"Agent Runtime: {len(self.runtime._agent_configs)} agents loaded")
            except Exception as e:
                logger.warning(f"Agent Runtime init skipped: {e}")

        # 初始化定时调度器
        if with_scheduler:
            try:
                try:
                    from .scheduler import AgentScheduleLoader
                except ImportError:
                    from scheduler import AgentScheduleLoader
                loader = AgentScheduleLoader(self.scheduler, self.runtime)
                for agent in self.registry.list_all():
                    loader.load_from_agent(agent.config)
                logger.info(f"Cron Scheduler: {len(self.scheduler._tasks)} scheduled tasks")
            except Exception as e:
                logger.warning(f"Scheduler init skipped: {e}")

        logger.info("=" * 60)
        logger.info("Engine initialized successfully")
        logger.info(f"  Agents: {len(self.registry.agents)}")
        logger.info(f"  TaskFlows: {len(self.taskflow_engine.taskflows)}")
        logger.info(f"  Webhook Routes: {len(self.webhook_gateway.routes)}")
        logger.info("=" * 60)

    async def start(self, with_server: bool = False, host: str = "0.0.0.0", port: int = 8080):
        """启动引擎（含所有子系统）"""
        self.running = True
        logger.info("Engine starting all subsystems...")

        # 启动 Cron Scheduler
        if self._scheduler:
            self._tasks.append(asyncio.create_task(self.scheduler.start()))

        # 启动 HTTP Server
        if with_server:
            try:
                from .server import run_server
            except ImportError:
                from server import run_server
            webhook_secret = self.cluster_config.get("webhook", {}).get("webhook_secret", "")
            self._tasks.append(asyncio.create_task(
                asyncio.to_thread(run_server, self, host, port, webhook_secret)
            ))
            logger.info(f"HTTP Server starting on {host}:{port}")

        logger.info("Engine started. All subsystems running.")

        # 保持运行
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """停止引擎"""
        self.running = False

        # 停止调度器
        if self._scheduler:
            await self.scheduler.stop()

        # 取消所有后台任务
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        logger.info("Engine stopped")

    async def execute_taskflow(self, tf_id: str, input_data: dict = None) -> dict:
        """手动执行TaskFlow"""
        return await self.taskflow_engine.execute(tf_id, input_data)

    async def execute_agent(self, agent_id: str, action: str, input_data: dict = None) -> dict:
        """通过 Runtime 执行 Agent"""
        return await self.runtime.execute_agent(agent_id, action, input_data)

    async def dispatch_event(self, event: Event) -> dict:
        """分发事件"""
        return await self.webhook_gateway.handle_event(event)

    def get_status(self) -> dict:
        """获取引擎状态"""
        agents_by_layer = {}
        for agent in self.registry.list_all():
            layer = agent.layer
            if layer not in agents_by_layer:
                agents_by_layer[layer] = []
            agents_by_layer[layer].append({
                "id": agent.id,
                "name": agent.name,
                "status": agent.status.value,
            })

        status = {
            "engine": "running" if self.running else "stopped",
            "total_agents": len(self.registry.agents),
            "total_taskflows": len(self.taskflow_engine.taskflows),
            "total_webhook_routes": len(self.webhook_gateway.routes),
            "agents_by_layer": agents_by_layer,
        }

        if self._scheduler:
            status["scheduler"] = self.scheduler.get_status()

        return status

    def print_status(self):
        """打印引擎状态"""
        status = self.get_status()
        print("\n" + "=" * 60)
        print("OpenClaw 智能体集群状态")
        print("=" * 60)
        print(f"Engine: {status['engine']}")
        print(f"Total Agents: {status['total_agents']}")
        print(f"Total TaskFlows: {status['total_taskflows']}")
        print(f"Webhook Routes: {status['total_webhook_routes']}")
        print("-" * 60)
        for layer, agents in status["agents_by_layer"].items():
            print(f"\n[{layer.upper()}]")
            for a in agents:
                print(f"  {a['id']:30s} [{a['status']}]")

        if "scheduler" in status:
            print("\n--- Scheduled Tasks ---")
            for t in status["scheduler"]["tasks"]:
                next_run = t["next_run"] or "N/A"
                print(f"  {t['id']:40s} next={next_run} [{t['status']}]")
        print("=" * 60)


# ============================================================
# CLI 入口
# ============================================================
async def main():
    """主入口"""
    engine = OrchestrationEngine()

    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description="OpenClaw Agent Cluster Engine")
    parser.add_argument("command", nargs="?", default="status",
                        choices=["status", "agents", "taskflows", "execute", "agent", "start", "serve", "test"])
    parser.add_argument("target", nargs="?", help="TaskFlow ID or Agent ID")
    parser.add_argument("--action", "-a", default="", help="Agent action")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Server port")
    parser.add_argument("--no-runtime", action="store_true", help="Skip Agent Runtime")
    parser.add_argument("--no-scheduler", action="store_true", help="Skip Cron Scheduler")
    args = parser.parse_args()

    # 初始化
    engine.initialize(
        with_runtime=not args.no_runtime,
        with_scheduler=not args.no_scheduler,
    )

    # 处理CLI命令
    if args.command == "status":
        engine.print_status()

    elif args.command == "agents":
        print("\nRegistered Agents:")
        print("-" * 80)
        for agent in sorted(engine.registry.list_all(), key=lambda a: (a.layer, a.priority)):
            print(f"  [{agent.layer:15s}] {agent.id:30s} p{agent.priority} {agent.description}")
        print("-" * 80)
        print(f"Total: {len(engine.registry.agents)} agents")

    elif args.command == "taskflows":
        print("\nRegistered TaskFlows:")
        print("-" * 80)
        for tf_id, tf in sorted(engine.taskflow_engine.taskflows.items()):
            print(f"  [{tf.priority:8s}] {tf_id:30s} ({len(tf.steps)} steps) {tf.description}")
        print("-" * 80)
        print(f"Total: {len(engine.taskflow_engine.taskflows)} taskflows")

    elif args.command == "execute":
        if not args.target:
            print("Usage: python engine.py execute <taskflow_id>")
            return
        tf_id = args.target
        print(f"\nExecuting TaskFlow: {tf_id}")
        print("-" * 40)
        result = await engine.execute_taskflow(tf_id)
        print(f"\nResult: {json.dumps(result, indent=2, default=str, ensure_ascii=False)}")

    elif args.command == "agent":
        if not args.target:
            print("Usage: python engine.py agent <agent_id> --action <action>")
            return
        action = args.action or "execute"
        print(f"\nExecuting Agent: {args.target} action={action}")
        print("-" * 40)
        result = await engine.execute_agent(args.target, action)
        print(f"\nResult: {json.dumps(result, indent=2, default=str, ensure_ascii=False)}")

    elif args.command == "test":
        print("\nRunning integration test...")
        await _run_integration_test(engine)

    elif args.command in ("start", "serve"):
        # 注册信号处理
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))
        await engine.start(with_server=True, host=args.host, port=args.port)

    else:
        engine.print_status()
        print(f"\nUsage: python engine.py [status|agents|taskflows|execute|agent|start|serve|test]")


async def _run_integration_test(engine: OrchestrationEngine):
    """集成测试"""
    results = []

    # 1. 测试 TaskFlow 加载
    print("  [1/5] Testing TaskFlow loading...")
    assert len(engine.taskflow_engine.taskflows) > 0, "No taskflows loaded"
    results.append(("TaskFlow loading", True))

    # 2. 测试 Agent Registry
    print("  [2/5] Testing Agent Registry...")
    assert len(engine.registry.agents) > 0, "No agents registered"
    ceo = engine.registry.get("ceo_agent")
    assert ceo is not None, "CEO Agent not found"
    results.append(("Agent Registry", True))

    # 3. 测试 Webhook Routes
    print("  [3/5] Testing Webhook Routes...")
    assert len(engine.webhook_gateway.routes) > 0, "No webhook routes"
    results.append(("Webhook Routes", True))

    # 4. 测试 Event Dispatch
    print("  [4/5] Testing Event Dispatch...")
    event = Event(id="test-001", source="test", name="test.event", data={"msg": "hello"})
    dispatch_result = await engine.dispatch_event(event)
    assert dispatch_result is not None, "Event dispatch failed"
    results.append(("Event Dispatch", True))

    # 5. 测试 TaskFlow 执行
    print("  [5/5] Testing TaskFlow execution...")
    tf_result = await engine.execute_taskflow("financial_management")
    assert tf_result is not None, "TaskFlow execution failed"
    results.append(("TaskFlow Execution", True))

    # 汇总
    print("\n" + "=" * 60)
    print("Integration Test Results:")
    print("-" * 60)
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False
    print("=" * 60)
    if all_passed:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED!")


if __name__ == "__main__":
    asyncio.run(main())
