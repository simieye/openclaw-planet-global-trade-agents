"""
Unified Engine - 统一调度引擎
整合 AgentRuntimeV2 + ConnectorHub + WebhookHandler + TaskFlowEngineV2
提供完整的 OpenClaw 智能体集群运行环境
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 确保项目根目录在 sys.path 中（支持直接脚本运行和包导入）
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 导入所有核心模块
try:
    from orchestration.runtime_v2 import AgentRuntimeV2
    from orchestration.connectors_hub import ConnectorHub
    from orchestration.webhook_handler import WebhookHandler
    from orchestration.taskflow_engine_v2 import TaskFlowEngineV2
    from orchestration.agent_brain import AgentBrain, AgentCluster, SkillRegistry, AgentMemory, MemoryType
    from orchestration.monitor import MonitorService
    from orchestration.scheduler import CronScheduler, AgentScheduleLoader
except ImportError:
    from .runtime_v2 import AgentRuntimeV2
    from .connectors_hub import ConnectorHub
    from .webhook_handler import WebhookHandler
    from .taskflow_engine_v2 import TaskFlowEngineV2
    from .agent_brain import AgentBrain, AgentCluster, SkillRegistry, AgentMemory, MemoryType
    from .monitor import MonitorService
    from .scheduler import CronScheduler, AgentScheduleLoader

logger = logging.getLogger("openclaw.unified")


class UnifiedEngine:
    """统一调度引擎 - 所有子系统的集成入口"""

    def __init__(self, base_path: str = None, env_config: dict = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.env_config = env_config or {}

        # 加载环境变量
        self._load_env()

        # 核心子系统
        self.connector_hub: Optional[ConnectorHub] = None
        self.runtime: Optional[AgentRuntimeV2] = None
        self.webhook_handler: Optional[WebhookHandler] = None
        self.taskflow_engine: Optional[TaskFlowEngineV2] = None
        self.monitor: Optional[MonitorService] = None
        self.scheduler: Optional[CronScheduler] = None

        # 状态
        self.running = False
        self._tasks: list[asyncio.Task] = []
        self._initialized = False

    def _load_env(self):
        """加载环境变量"""
        try:
            from dotenv import load_dotenv
            env_file = self.base_path / ".env"
            if env_file.exists():
                load_dotenv(env_file)
        except ImportError:
            pass

        # 合并环境变量到配置
        env_map = {
            "SHOPIFY_STORE_URL": "SHOPIFY_STORE_URL",
            "SHOPIFY_ACCESS_TOKEN": "SHOPIFY_ACCESS_TOKEN",
            "AMAZON_SELLER_ID": "AMAZON_SELLER_ID",
            "AMAZON_ACCESS_TOKEN": "AMAZON_ACCESS_TOKEN",
            "TIKTOK_APP_KEY": "TIKTOK_APP_KEY",
            "TIKTOK_APP_SECRET": "TIKTOK_APP_SECRET",
            "WHATSAPP_PHONE_NUMBER_ID": "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_ACCESS_TOKEN": "WHATSAPP_ACCESS_TOKEN",
            "SENDGRID_API_KEY": "SENDGRID_API_KEY",
            "HEYGEN_API_KEY": "HEYGEN_API_KEY",
            "STRIPE_API_KEY": "STRIPE_API_KEY",
            "DHL_API_KEY": "DHL_API_KEY",
            "UPS_CLIENT_ID": "UPS_CLIENT_ID",
            "UPS_CLIENT_SECRET": "UPS_CLIENT_SECRET",
            "FEDEX_API_KEY": "FEDEX_API_KEY",
            "FEDEX_SECRET_KEY": "FEDEX_SECRET_KEY",
            "GOOGLE_ADS_DEVELOPER_TOKEN": "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CLIENT_ID": "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET": "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN": "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_CUSTOMER_ID": "GOOGLE_ADS_CUSTOMER_ID",
            "META_ADS_ACCESS_TOKEN": "META_ADS_ACCESS_TOKEN",
            "META_ADS_ACCOUNT_ID": "META_ADS_ACCOUNT_ID",
            "GA4_PROPERTY_ID": "GA4_PROPERTY_ID",
            "WECHAT_WORK_CORP_ID": "WECHAT_WORK_CORP_ID",
            "WECHAT_WORK_CORP_SECRET": "WECHAT_WORK_CORP_SECRET",
            "FEISHU_APP_ID": "FEISHU_APP_ID",
            "FEISHU_APP_SECRET": "FEISHU_APP_SECRET",
            "LINKEDIN_CLIENT_ID": "LINKEDIN_CLIENT_ID",
            "LINKEDIN_CLIENT_SECRET": "LINKEDIN_CLIENT_SECRET",
            "OPENAI_API_KEY": "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
        }
        for env_key, config_key in env_map.items():
            val = os.environ.get(env_key, "")
            if val and config_key not in self.env_config:
                self.env_config[config_key] = val

    async def initialize(self):
        """初始化所有子系统"""
        if self._initialized:
            return

        logger.info("=" * 60)
        logger.info("🦞 OpenClaw Unified Engine - 龙虾星球共创联盟")
        logger.info("=" * 60)

        # 1. 初始化连接器中心
        logger.info("[1/7] Initializing Connector Hub...")
        self.connector_hub = ConnectorHub(self.env_config)
        await self.connector_hub.initialize()
        logger.info(f"  Connectors: {len(self.connector_hub.get_all())}")

        # 2. 初始化Agent运行时
        logger.info("[2/7] Initializing Agent Runtime V2...")
        self.runtime = AgentRuntimeV2(self.base_path, self.env_config)
        self.runtime.load_all_agents()
        logger.info(f"  Agents loaded: {len(self.runtime._agent_brains)}")

        # 3. 初始化Webhook处理器
        logger.info("[3/7] Initializing Webhook Handler...")
        self.webhook_handler = WebhookHandler(
            runtime=self.runtime,
            connector_hub=self.connector_hub,
        )
        logger.info(f"  Webhook routes: {len(self.webhook_handler._handlers)}")

        # 4. 初始化TaskFlow引擎
        logger.info("[4/7] Initializing TaskFlow Engine V2...")
        self.taskflow_engine = TaskFlowEngineV2(
            runtime=self.runtime,
            webhook_handler=self.webhook_handler,
        )
        logger.info(f"  TaskFlows: {len(self.taskflow_engine._flow_definitions)}")

        # 5. 初始化监控服务
        logger.info("[5/7] Initializing Monitor Service...")
        self.monitor = MonitorService()

        # 6. 初始化定时调度器
        logger.info("[6/7] Initializing Cron Scheduler...")
        self.scheduler = CronScheduler()
        schedule_loader = AgentScheduleLoader(self.scheduler, self.runtime)
        for agent_id, config in self.runtime._agent_configs.items():
            try:
                schedule_loader.load_from_agent(config)
            except Exception as e:
                logger.debug(f"No schedule for {agent_id}: {e}")
        logger.info(f"  Scheduled tasks: {len(self.scheduler._tasks)}")

        self._initialized = True

        logger.info("=" * 60)
        logger.info("✅ Unified Engine Initialized")
        logger.info(f"   Agents: {len(self.runtime._agent_brains)}")
        logger.info(f"   Connectors: {len(self.connector_hub.get_all())}")
        logger.info(f"   Webhooks: {len(self.webhook_handler._handlers)}")
        logger.info(f"   TaskFlows: {len(self.taskflow_engine._flow_definitions)}")
        logger.info("=" * 60)

    async def start(self, with_server: bool = False, host: str = "0.0.0.0", port: int = 8080):
        """启动引擎"""
        if not self._initialized:
            await self.initialize()

        self.running = True
        logger.info("🚀 Starting Unified Engine...")

        # 启动定时调度器
        if self.scheduler:
            self._tasks.append(asyncio.create_task(self.scheduler.start()))
            logger.info("  Scheduler: started")

        # 启动监控服务
        if self.monitor:
            self._tasks.append(asyncio.create_task(self.monitor.start()))
            logger.info("  Monitor: started")

        # 启动HTTP服务器
        if with_server:
            try:
                from .server_v2 import create_app_v2, run_server_v2
            except ImportError:
                from orchestration.server_v2 import create_app_v2, run_server_v2

            self._tasks.append(asyncio.create_task(
                asyncio.to_thread(run_server_v2, self, host, port)
            ))
            logger.info(f"  HTTP Server: http://{host}:{port}")

        logger.info("✅ Unified Engine running. All systems operational.")
        logger.info("=" * 60)

        # 保持运行
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """停止引擎"""
        logger.info("🛑 Stopping Unified Engine...")
        self.running = False

        if self.scheduler:
            await self.scheduler.stop()
        if self.monitor:
            await self.monitor.stop()
        if self.connector_hub:
            await self.connector_hub.close_all()

        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        logger.info("✅ Unified Engine stopped")

    # ---- 便捷API ----

    async def execute_agent(self, agent_id: str, action: str, data: dict = None) -> dict:
        """执行单个Agent"""
        return await self.runtime.execute_agent(agent_id, action, data)

    async def execute_taskflow(self, flow_id: str, data: dict = None) -> dict:
        """执行TaskFlow"""
        return await self.taskflow_engine.execute(flow_id, data)

    async def process_webhook(self, route_id: str, data: dict) -> dict:
        """处理Webhook事件"""
        return await self.webhook_handler.process(route_id, data)

    async def route_event(self, event_name: str, data: dict, source: str = "") -> dict:
        """路由事件到合适的Agent"""
        # 通过 webhook_handler 的 process 处理事件
        return await self.webhook_handler.process(source, {
            "event": event_name,
            "data": data,
            "source": source,
        })

    def get_status(self) -> dict:
        """获取完整系统状态"""
        return {
            "engine": "running" if self.running else "stopped",
            "version": "3.0.0",
            "timestamp": datetime.now().isoformat(),
            "agents": {
                "total": len(self.runtime._agent_brains) if self.runtime else 0,
                "by_layer": self._get_agents_by_layer(),
            },
            "connectors": self.connector_hub.get_all() if self.connector_hub else {},
            "webhooks": self.webhook_handler.get_stats() if self.webhook_handler else {},
            "taskflows": {
                "total": len(self.taskflow_engine._flow_definitions) if self.taskflow_engine else 0,
            },
            "cluster": self.runtime.get_cluster_status() if self.runtime else {},
        }

    def _get_agents_by_layer(self) -> dict:
        if not self.runtime:
            return {}
        layers = {}
        for aid, brain in self.runtime._agent_brains.items():
            config = self.runtime.get_agent_config(aid) or {}
            agent_info = config.get("agent", {})
            layer = agent_info.get("layer", "unknown")
            if layer not in layers:
                layers[layer] = []
            layers[layer].append({
                "id": aid,
                "name": agent_info.get("name", aid),
                "tasks_completed": brain.metrics.get("tasks_completed", 0),
                "last_active": brain.metrics.get("last_active", ""),
            })
        return layers

    async def get_dashboard_data(self) -> dict:
        """获取Dashboard实时数据"""
        return {
            "timestamp": datetime.now().isoformat(),
            "version": "3.0.0",
            "engine_status": "running" if self.running else "stopped",
            "total_agents": len(self.runtime._agent_brains) if self.runtime else 0,
            "total_connectors": len(self.connector_hub.get_all()) if self.connector_hub else 0,
            "total_webhooks": len(self.webhook_handler._handlers) if self.webhook_handler else 0,
            "total_taskflows": len(self.taskflow_engine._flow_definitions) if self.taskflow_engine else 0,
            "system_status": self.get_status(),
        }


# ============================================================
# CLI Entry Point
# ============================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="OpenClaw Unified Engine")
    parser.add_argument("command", nargs="?", default="status",
                        choices=["status", "start", "serve", "agents", "taskflows", "webhooks",
                                 "execute", "agent", "event", "test"])
    parser.add_argument("target", nargs="?", help="TaskFlow ID or Agent ID")
    parser.add_argument("--action", "-a", default="execute", help="Agent action")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Server port")
    parser.add_argument("--data", "-d", default="{}", help="JSON input data")
    args = parser.parse_args()

    engine = UnifiedEngine()

    if args.command == "status":
        await engine.initialize()
        status = engine.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False, default=str))

    elif args.command == "agents":
        await engine.initialize()
        print(f"\n🦞 Registered Agents ({len(engine.runtime._agent_brains)}):")
        print("-" * 80)
        for aid, brain in sorted(engine.runtime._agent_brains.items()):
            config = engine.runtime.get_agent_config(aid) or {}
            agent_info = config.get("agent", {})
            tasks = brain.metrics.get("tasks_completed", 0)
            tokens = brain.metrics.get("total_tokens", 0)
            print(f"  [{agent_info.get('layer', '?'):20s}] {aid:30s} "
                  f"tasks={tasks} tokens={tokens}")
        print("-" * 80)

    elif args.command == "taskflows":
        await engine.initialize()
        print(f"\n🦞 Registered TaskFlows ({len(engine.taskflow_engine._flow_definitions)}):")
        print("-" * 80)
        for fid, fdef in engine.taskflow_engine._flow_definitions.items():
            name = fdef.get("name", fid)
            steps = len(fdef.get("steps", []))
            print(f"  {fid:35s} {name:30s} ({steps} steps)")
        print("-" * 80)

    elif args.command == "webhooks":
        await engine.initialize()
        stats = engine.webhook_handler.get_stats()
        print(f"\n🦞 Webhook Routes: {stats.get('total_handlers', 0)}")
        print(f"   Processed: {stats.get('events_processed', 0)}")
        print(f"   Failed: {stats.get('events_failed', 0)}")

    elif args.command == "execute":
        if not args.target:
            print("Usage: python unified_engine.py execute <taskflow_id>")
            return
        await engine.initialize()
        data = json.loads(args.data) if args.data else {}
        print(f"\n🚀 Executing TaskFlow: {args.target}")
        result = await engine.execute_taskflow(args.target, data)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "agent":
        if not args.target:
            print("Usage: python unified_engine.py agent <agent_id> --action <action>")
            return
        await engine.initialize()
        data = json.loads(args.data) if args.data else {}
        print(f"\n🤖 Executing Agent: {args.target} action={args.action}")
        result = await engine.execute_agent(args.target, args.action, data)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "event":
        if not args.target:
            print("Usage: python unified_engine.py event <event_name> --data '{}'")
            return
        await engine.initialize()
        data = json.loads(args.data) if args.data else {}
        print(f"\n📨 Routing Event: {args.target}")
        result = await engine.route_event(args.target, data)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "test":
        await engine.initialize()
        print("\n🧪 Running Integration Tests...")
        await _run_tests(engine)

    elif args.command in ("start", "serve"):
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))
            except NotImplementedError:
                pass
        await engine.start(with_server=True, host=args.host, port=args.port)


async def _run_tests(engine: UnifiedEngine):
    """集成测试"""
    results = []

    # Test 1: Agent execution
    print("  [1/6] Testing Agent execution...")
    try:
        r = await engine.execute_agent("ceo_agent", "generate_daily_report")
        results.append(("Agent Execution", True, r.get("status", "unknown")))
    except Exception as e:
        results.append(("Agent Execution", False, str(e)))

    # Test 2: TaskFlow execution
    print("  [2/6] Testing TaskFlow execution...")
    try:
        r = await engine.execute_taskflow("financial_management")
        status = r.get("status", "unknown") if isinstance(r, dict) else "unknown"
        results.append(("TaskFlow Execution", True, status))
    except Exception as e:
        results.append(("TaskFlow Execution", False, str(e)))

    # Test 3: Webhook processing
    print("  [3/6] Testing Webhook processing...")
    try:
        r = await engine.process_webhook("crm", {
            "event": "new_lead",
            "data": {"lead_id": "test-001", "source": "website"}
        })
        status = r.get("status", "unknown") if isinstance(r, dict) else "unknown"
        results.append(("Webhook Processing", True, status))
    except Exception as e:
        results.append(("Webhook Processing", False, str(e)))

    # Test 4: Event routing
    print("  [4/6] Testing Event routing...")
    try:
        r = await engine.route_event("new_lead", {"lead_id": "test-002", "contact": {"email": "test@test.com"}})
        status = r.get("status", "unknown") if isinstance(r, dict) else "unknown"
        results.append(("Event Routing", True, status))
    except Exception as e:
        results.append(("Event Routing", False, str(e)))

    # Test 5: Dashboard data
    print("  [5/6] Testing Dashboard data...")
    try:
        data = await engine.get_dashboard_data()
        assert data.get("total_agents", 0) > 0, "No agents in dashboard"
        results.append(("Dashboard Data", True))
    except Exception as e:
        results.append(("Dashboard Data", False, str(e)))

    # Test 6: Connector hub
    print("  [6/6] Testing Connector Hub...")
    try:
        connectors = engine.connector_hub.get_all()
        results.append(("Connector Hub", True, f"{len(connectors)} connectors"))
    except Exception as e:
        results.append(("Connector Hub", False, str(e)))

    # Summary
    print("\n" + "=" * 60)
    print("Integration Test Results:")
    print("-" * 60)
    all_passed = True
    for item in results:
        name = item[0]
        passed = item[1]
        extra = item[2] if len(item) > 2 else ""
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  [{status}] {name} {extra}")
        if not passed:
            all_passed = False
    print("=" * 60)
    if all_passed:
        print("🎉 All tests PASSED!")
    else:
        print("⚠️  Some tests FAILED!")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
