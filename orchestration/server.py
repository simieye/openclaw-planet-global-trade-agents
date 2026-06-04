"""
OpenClaw HTTP API Server
FastAPI 服务器 - Webhook 接收、API 路由、Agent 触发
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

try:
    from .engine import OrchestrationEngine, Event
except ImportError:
    from orchestration.engine import OrchestrationEngine, Event

logger = logging.getLogger("openclaw.server")

# ============================================================
# Pydantic Models
# ============================================================

class AgentTriggerRequest(BaseModel):
    action: str
    data: dict = Field(default_factory=dict)
    async_mode: bool = True


class TaskFlowExecuteRequest(BaseModel):
    input_data: dict = Field(default_factory=dict)
    async_mode: bool = True


class WebhookEvent(BaseModel):
    event: str
    source: str = ""
    data: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    agents_count: int
    taskflows_count: int


class EngineStatusResponse(BaseModel):
    engine: str
    total_agents: int
    total_taskflows: int
    total_webhook_routes: int
    agents_by_layer: dict


# ============================================================
# FastAPI Application
# ============================================================

engine: Optional[OrchestrationEngine] = None
start_time: Optional[datetime] = None
webhook_secret: str = ""


def get_engine() -> OrchestrationEngine:
    global engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return engine


def create_app(_engine: OrchestrationEngine, _webhook_secret: str = "") -> FastAPI:
    global engine, webhook_secret, start_time
    engine = _engine
    webhook_secret = _webhook_secret
    start_time = datetime.now()

    app = FastAPI(
        title="OpenClaw Agent Cluster API",
        description="跨境电商品牌出海智能体集群系统 API",
        version="1.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ============================================================
    # Health & Status
    # ============================================================

    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        eng = get_engine()
        uptime = (datetime.now() - start_time).total_seconds()
        return HealthResponse(
            status="healthy",
            version="1.0.0",
            uptime_seconds=uptime,
            agents_count=len(eng.registry.agents),
            taskflows_count=len(eng.taskflow_engine.taskflows),
        )

    @app.get("/api/status", response_model=EngineStatusResponse)
    async def engine_status():
        return get_engine().get_status()

    @app.get("/api/agents")
    async def list_agents(layer: str = None):
        eng = get_engine()
        if layer:
            agents = eng.registry.get_by_layer(layer)
        else:
            agents = eng.registry.list_all()
        return {
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "layer": a.layer,
                    "description": a.description,
                    "priority": a.priority,
                    "status": a.status.value,
                    "triggers": a.triggers,
                }
                for a in agents
            ]
        }

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str):
        eng = get_engine()
        agent = eng.registry.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        return {
            "id": agent.id,
            "name": agent.name,
            "layer": agent.layer,
            "description": agent.description,
            "priority": agent.priority,
            "status": agent.status.value,
            "triggers": agent.triggers,
            "config": agent.config,
        }

    @app.get("/api/taskflows")
    async def list_taskflows():
        eng = get_engine()
        return {
            "taskflows": [
                {
                    "id": tf_id,
                    "name": tf.name,
                    "description": tf.description,
                    "priority": tf.priority,
                    "trigger": tf.trigger,
                    "status": tf.status.value,
                    "steps_count": len(tf.steps),
                }
                for tf_id, tf in eng.taskflow_engine.taskflows.items()
            ]
        }

    @app.get("/api/taskflows/{tf_id}")
    async def get_taskflow(tf_id: str):
        eng = get_engine()
        tf = eng.taskflow_engine.taskflows.get(tf_id)
        if not tf:
            raise HTTPException(status_code=404, detail=f"TaskFlow not found: {tf_id}")
        return {
            "id": tf.id,
            "name": tf.name,
            "description": tf.description,
            "priority": tf.priority,
            "trigger": tf.trigger,
            "status": tf.status.value,
            "steps": [
                {
                    "order": s.order,
                    "agent_id": s.agent_id,
                    "action": s.action,
                    "input_from": s.input_from,
                    "output_to": s.output_to,
                    "timeout_seconds": s.timeout_seconds,
                    "condition": s.condition,
                }
                for s in tf.steps
            ],
        }

    # ============================================================
    # Agent Trigger
    # ============================================================

    @app.post("/api/agents/{agent_id}/trigger")
    async def trigger_agent(
        agent_id: str,
        req: AgentTriggerRequest,
        background_tasks: BackgroundTasks,
    ):
        eng = get_engine()
        agent = eng.registry.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

        event_id = f"api-{uuid.uuid4().hex[:8]}"
        event = Event(
            id=event_id,
            source="api",
            name=f"agent.{agent_id}.triggered",
            data={"action": req.action, **req.data},
        )

        if req.async_mode:
            background_tasks.add_task(eng.webhook_gateway._trigger_agent, agent_id, {"action": req.action}, event)
            return {"status": "triggered", "agent": agent_id, "event_id": event_id, "mode": "async"}
        else:
            result = await eng.webhook_gateway._trigger_agent(agent_id, {"action": req.action}, event)
            return {"status": "completed", "agent": agent_id, "result": result}

    # ============================================================
    # TaskFlow Execute
    # ============================================================

    @app.post("/api/taskflows/{tf_id}/execute")
    async def execute_taskflow(
        tf_id: str,
        req: TaskFlowExecuteRequest,
        background_tasks: BackgroundTasks,
    ):
        eng = get_engine()
        if tf_id not in eng.taskflow_engine.taskflows:
            raise HTTPException(status_code=404, detail=f"TaskFlow not found: {tf_id}")

        if req.async_mode:
            background_tasks.add_task(eng.execute_taskflow, tf_id, req.input_data)
            return {"status": "started", "taskflow": tf_id, "mode": "async"}
        else:
            result = await eng.execute_taskflow(tf_id, req.input_data)
            return {"status": "completed", "taskflow": tf_id, "result": result}

    # ============================================================
    # Webhook Endpoints
    # ============================================================

    async def verify_webhook_signature(request: Request) -> bool:
        """验证 Webhook HMAC 签名"""
        if not webhook_secret:
            return True  # 未配置secret时跳过验证
        signature = request.headers.get("X-Webhook-Signature", "")
        if not signature:
            return False
        body = await request.body()
        expected = hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    @app.post("/webhooks/{source}")
    async def handle_webhook(
        source: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ):
        # 验证签名（可选）
        # if not await verify_webhook_signature(request):
        #     raise HTTPException(status_code=401, detail="Invalid webhook signature")

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        event_name = body.get("event", body.get("type", "unknown"))
        event_data = body.get("data", body)

        event = Event(
            id=f"wh-{uuid.uuid4().hex[:8]}",
            source=source,
            name=event_name,
            data=event_data,
            timestamp=datetime.now(),
        )

        logger.info(f"Webhook received: {source}/{event_name}")
        background_tasks.add_task(engine.webhook_gateway.handle_event, event)

        return {"status": "accepted", "event_id": event.id, "source": source, "event": event_name}

    # ============================================================
    # Event API
    # ============================================================

    @app.post("/api/events")
    async def publish_event(req: WebhookEvent, background_tasks: BackgroundTasks):
        eng = get_engine()
        event = Event(
            id=f"api-evt-{uuid.uuid4().hex[:8]}",
            source=req.source or "api",
            name=req.event,
            data=req.data,
        )
        background_tasks.add_task(eng.dispatch_event, event)
        return {"status": "dispatched", "event_id": event.id}

    # ============================================================
    # Metrics
    # ============================================================

    @app.get("/metrics")
    async def metrics():
        eng = get_engine()
        status = eng.get_status()
        return {
            "openclaw_agents_total": status["total_agents"],
            "openclaw_taskflows_total": status["total_taskflows"],
            "openclaw_webhook_routes_total": status["total_webhook_routes"],
            "openclaw_engine_status": 1 if status["engine"] == "running" else 0,
        }

    return app


def run_server(
    _engine: OrchestrationEngine,
    host: str = "0.0.0.0",
    port: int = 8080,
    _webhook_secret: str = "",
):
    """启动 HTTP 服务器"""
    app = create_app(_engine, _webhook_secret)
    logger.info(f"Starting OpenClaw API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
