"""
Server v2 - 统一引擎 HTTP API 服务器
FastAPI 服务器 - Dashboard 管理面板 + REST API + Webhook 接收 + Agent 触发
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger("openclaw.server_v2")


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


class WebhookEventRequest(BaseModel):
    event: str
    source: str = ""
    data: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    agents_count: int
    taskflows_count: int


# ============================================================
# App Factory
# ============================================================

_engine = None
_start_time: Optional[datetime] = None


def create_app_v2(engine, host: str = "0.0.0.0", port: int = 8080) -> FastAPI:
    """创建 FastAPI 应用（v2 - 支持 Dashboard）"""
    global _engine, _start_time
    _engine = engine
    _start_time = datetime.now()

    app = FastAPI(
        title="OpenClaw Unified Engine API v2",
        description="🦞 龙虾星球共创联盟 - 跨境电商品牌出海智能体集群系统",
        version="3.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files - Dashboard
    dashboard_path = Path(engine.base_path) / "dashboard"
    if dashboard_path.exists():
        app.mount("/static", StaticFiles(directory=str(dashboard_path / "static")), name="static")

    # ============================================================
    # Dashboard Pages
    # ============================================================

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home():
        """管理驾驶舱主页"""
        html_path = dashboard_path / "index.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head><meta charset="UTF-8"><title>OpenClaw 管理驾驶舱</title></head>
        <body style="font-family:system-ui;margin:40px;background:#0a0a0a;color:#e0e0e0">
            <h1>🦞 OpenClaw 统一引擎</h1>
            <p>Dashboard 页面未找到。请确保 <code>dashboard/index.html</code> 存在。</p>
            <p><a href="/api/status" style="color:#4fc3f7">查看 API 状态</a></p>
        </body>
        </html>
        """)

    @app.get("/enterprise-os", response_class=HTMLResponse)
    async def enterprise_os():
        """企业操作系统面板"""
        html_path = dashboard_path / "enterprise-os.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return HTMLResponse(content="<h1>Enterprise OS 面板未找到</h1>", status_code=404)

    # ============================================================
    # Health & Status
    # ============================================================

    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        uptime = (datetime.now() - _start_time).total_seconds()
        status = _engine.get_status()
        return HealthResponse(
            status="healthy",
            version="3.0.0",
            uptime_seconds=uptime,
            agents_count=status.get("agents", {}).get("total", 0),
            taskflows_count=status.get("taskflows", {}).get("total", 0),
        )

    @app.get("/api/status")
    async def engine_status():
        return _engine.get_status()

    @app.get("/api/dashboard")
    async def get_dashboard():
        """获取 Dashboard 实时数据"""
        return await _engine.get_dashboard_data()

    # ============================================================
    # Agent APIs
    # ============================================================

    @app.get("/api/agents")
    async def list_agents(layer: str = None):
        status = _engine.get_status()
        agents = status.get("agents", {}).get("by_layer", {})
        if layer:
            return {"agents": agents.get(layer, [])}
        return {"agents": agents, "total": status.get("agents", {}).get("total", 0)}

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str):
        config = _engine.runtime.get_agent_config(agent_id) if _engine.runtime else None
        brain = _engine.runtime.get_agent_brain(agent_id) if _engine.runtime else None
        if not config and not brain:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        return {
            "id": agent_id,
            "config": config or {},
            "metrics": brain.metrics if brain else {},
        }

    @app.post("/api/agents/{agent_id}/trigger")
    async def trigger_agent(
        agent_id: str,
        req: AgentTriggerRequest,
        background_tasks: BackgroundTasks,
    ):
        if req.async_mode:
            background_tasks.add_task(_engine.execute_agent, agent_id, req.action, req.data)
            return {"status": "triggered", "agent": agent_id, "mode": "async"}
        else:
            result = await _engine.execute_agent(agent_id, req.action, req.data)
            return {"status": "completed", "agent": agent_id, "result": result}

    # ============================================================
    # TaskFlow APIs
    # ============================================================

    @app.get("/api/taskflows")
    async def list_taskflows():
        status = _engine.get_status()
        return status.get("taskflows", {})

    @app.post("/api/taskflows/{flow_id}/execute")
    async def execute_taskflow(
        flow_id: str,
        req: TaskFlowExecuteRequest,
        background_tasks: BackgroundTasks,
    ):
        if req.async_mode:
            background_tasks.add_task(_engine.execute_taskflow, flow_id, req.input_data)
            return {"status": "started", "taskflow": flow_id, "mode": "async"}
        else:
            result = await _engine.execute_taskflow(flow_id, req.input_data)
            return {"status": "completed", "taskflow": flow_id, "result": result}

    # ============================================================
    # Webhook Endpoints
    # ============================================================

    @app.post("/webhooks/{source}")
    async def handle_webhook(
        source: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        event_name = body.get("event", body.get("type", "unknown"))
        event_data = body.get("data", body)

        # 查找匹配的 webhook route
        processed = await _engine.process_webhook(source, {
            "event": event_name,
            "data": event_data,
            **body,
        })

        return {"status": "accepted", "source": source, "event": event_name, "result": processed}

    # ============================================================
    # Event API
    # ============================================================

    @app.post("/api/events")
    async def publish_event(req: WebhookEventRequest, background_tasks: BackgroundTasks):
        event_id = f"api-evt-{uuid.uuid4().hex[:8]}"
        result = await _engine.route_event(
            event_name=req.event,
            data=req.data,
            source=req.source or "api",
        )
        return {"status": "routed", "event_id": event_id, "result": result}

    # ============================================================
    # Connectors API
    # ============================================================

    @app.get("/api/connectors")
    async def list_connectors():
        if _engine.connector_hub:
            return {"connectors": _engine.connector_hub.get_all()}
        return {"connectors": {}}

    # ============================================================
    # Webhook Stats
    # ============================================================

    @app.get("/api/webhooks/stats")
    async def webhook_stats():
        if _engine.webhook_handler:
            return _engine.webhook_handler.get_stats()
        return {"total_handlers": 0, "events_processed": 0, "events_failed": 0}

    # ============================================================
    # Metrics (Prometheus compatible)
    # ============================================================

    @app.get("/metrics")
    async def metrics():
        status = _engine.get_status()
        agents_total = status.get("agents", {}).get("total", 0)
        taskflows_total = status.get("taskflows", {}).get("total", 0)
        return {
            "openclaw_agents_total": agents_total,
            "openclaw_taskflows_total": taskflows_total,
            "openclaw_engine_status": 1 if status.get("engine") == "running" else 0,
            "openclaw_version": "3.0.0",
        }

    return app


def run_server_v2(engine, host: str = "0.0.0.0", port: int = 8080):
    """启动 HTTP 服务器（v2）"""
    app = create_app_v2(engine, host, port)
    logger.info(f"🚀 Starting OpenClaw Unified Engine API v2 on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
