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
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
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


class KnowledgeLinkRequest(BaseModel):
    """知识库链接添加请求"""
    url: str
    kb_name: str = "默认知识库"
    link_type: str = "web"  # web / feishu

class BatchAddLinkToAgentsRequest(BaseModel):
    """批量给智能体添加知识库链接"""
    url: str
    link_type: str = "web"
    agent_ids: list = Field(default_factory=list)  # 空列表 = 全部智能体

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

    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        """登录注册页面"""
        html_path = dashboard_path / "login.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return HTMLResponse(content="<h1>登录页面未找到</h1>", status_code=404)

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
    # Chat API - Ollama 本地 LLM 聊天 + 流式输出
    # ============================================================

    class ChatRequest(BaseModel):
        message: str
        provider: str = "ollama"
        model: str = ""
        conversation_history: list = Field(default_factory=list)
        temperature: float = 0.7
        max_tokens: int = 4096
        system_prompt: str = ""

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        """与 AI 拍档聊天（非流式）"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        llm = _engine.runtime.llm_client

        # 构建 messages
        messages = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        else:
            messages.append({"role": "system", "content": "你是龙虾星球共创联盟的 AI 拍档，帮助用户解决跨境电商品牌出海的各种问题。用中文回答。"})

        # 加入历史对话
        for h in req.conversation_history[-10:]:  # 最多10轮历史
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        # 当前用户消息
        messages.append({"role": "user", "content": req.message})

        model = req.model or ""
        response = await llm.chat(
            provider=req.provider,
            model=model,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )

        return {
            "success": True,
            "response": response.content,
            "model": response.model,
            "tokens_used": response.tokens_used,
            "provider": req.provider,
        }

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest):
        """与 AI 拍档流式聊天（SSE）"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        llm = _engine.runtime.llm_client

        messages = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        else:
            messages.append({"role": "system", "content": "你是龙虾星球共创联盟的 AI 拍档，帮助用户解决跨境电商品牌出海的各种问题。用中文回答。"})

        for h in req.conversation_history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": req.message})

        async def event_generator():
            try:
                async for chunk in llm.chat_stream(
                    provider=req.provider,
                    model=req.model or "",
                    messages=messages,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                ):
                    yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/chat/test-agent")
    async def test_agent(agent_id: str = "", message: str = "请介绍一下你的能力"):
        """测试单个 Agent 功能 - 触发 Agent think 并返回结果"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")

        brain = _engine.runtime.get_agent_brain(agent_id)
        if not brain:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

        result = await brain.think(message, {"source": "chat_test"})
        return {
            "success": True,
            "agent_id": agent_id,
            "agent_name": brain.config.get("agent", {}).get("name", agent_id),
            "thinking": result.get("thinking", ""),
            "tokens_used": result.get("tokens_used", 0),
        }

    @app.get("/api/chat/ollama-models")
    async def list_ollama_models():
        """获取本地 Ollama 可用模型列表"""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {
                        "success": True,
                        "models": [{"name": m.get("name", ""), "size": m.get("size", 0)} for m in models],
                    }
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
        return {"success": False, "models": [], "error": "无法连接 Ollama 服务"}

    @app.get("/api/chat/ollama-status")
    async def ollama_status():
        """检查 Ollama 连接状态"""
        if _engine and _engine.runtime:
            ok = await _engine.runtime.llm_client.check_ollama()
            models = await _engine.runtime.llm_client.get_ollama_models()
            return {
                "connected": ok,
                "models_count": len(models),
                "models": [m.get("name") for m in models],
            }
        return {"connected": False, "models_count": 0, "models": []}

    # ============================================================
    # SOP TaskFlow Execution API - 真实执行 SOP 工作流
    # ============================================================

    class SOPExecuteRequest(BaseModel):
        taskflow_id: str = ""
        task_name: str = ""
        category: str = ""
        input_data: dict = Field(default_factory=dict)
        async_mode: bool = True

    @app.post("/api/sop/execute")
    async def execute_sop_taskflow(req: SOPExecuteRequest, background_tasks: BackgroundTasks):
        """执行 SOP TaskFlow - 调用 AI 模型执行跨境电商任务"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        task_name = req.task_name or req.taskflow_id
        category = req.category or "通用"

        # 构建 SOP 执行提示词
        system_prompt = _build_sop_system_prompt(category, task_name)
        user_prompt = _build_sop_user_prompt(category, task_name, req.input_data)

        if req.async_mode:
            background_tasks.add_task(
                _execute_sop_async, _engine, system_prompt, user_prompt, task_name
            )
            return {
                "status": "started",
                "taskflow_id": req.taskflow_id,
                "task_name": task_name,
                "category": category,
                "mode": "async",
            }
        else:
            result = await _execute_sop_sync(_engine, system_prompt, user_prompt, task_name)
            return result

    @app.post("/api/sop/execute-stream")
    async def execute_sop_stream(req: SOPExecuteRequest):
        """流式执行 SOP TaskFlow"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        task_name = req.task_name or req.taskflow_id
        category = req.category or "通用"
        system_prompt = _build_sop_system_prompt(category, task_name)
        user_prompt = _build_sop_user_prompt(category, task_name, req.input_data)

        llm = _engine.runtime.llm_client

        async def event_generator():
            yield f"data: {json.dumps({'status': 'started', 'task': task_name}, ensure_ascii=False)}\n\n"
            try:
                async for chunk in llm.chat_stream(
                    provider="ollama",
                    model="",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.7,
                    max_tokens=4096,
                ):
                    yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'status': 'completed'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/sop/agent-execute")
    async def sop_agent_execute(request: Request):
        """通过指定 Agent 执行 SOP 任务"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        body = await request.json()
        agent_id = body.get("agent_id", "")
        task_name = body.get("task_name", "")
        input_data = body.get("input_data", {})

        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")

        result = await _engine.runtime.think_agent(agent_id, json.dumps({
            "task": task_name,
            "input_data": input_data,
        }, ensure_ascii=False))

        return {
            "success": True,
            "agent_id": agent_id,
            "task_name": task_name,
            "thinking": result.get("thinking", ""),
            "tokens_used": result.get("tokens_used", 0),
        }

    # SOP 系统列表 API
    @app.get("/api/sop/systems")
    async def list_sop_systems():
        """列出所有 SOP 系统及其 TaskFlow"""
        systems = {
            "tiktokshop": {
                "name": "TikTok Shop 全球增长SOP",
                "icon": "🎵",
                "total": 30,
                "categories": [
                    {"id": "product", "name": "选品调研", "count": 5, "icon": "🔍"},
                    {"id": "content", "name": "内容创作", "count": 6, "icon": "🎬"},
                    {"id": "influencer", "name": "达人合作", "count": 4, "icon": "🌟"},
                    {"id": "live", "name": "直播运营", "count": 4, "icon": "📡"},
                    {"id": "ads", "name": "广告投放", "count": 4, "icon": "📢"},
                    {"id": "private", "name": "私域运营", "count": 3, "icon": "👥"},
                    {"id": "affiliate", "name": "联盟营销", "count": 2, "icon": "🤝"},
                    {"id": "growth", "name": "GMV增长飞轮", "count": 2, "icon": "🚀"},
                ],
            },
            "amazonbrand": {
                "name": "Amazon 品牌增长SOP",
                "icon": "📦",
                "total": 31,
                "categories": [
                    {"id": "product", "name": "选品调研", "count": 4, "icon": "🔍"},
                    {"id": "listing", "name": "Listing优化", "count": 5, "icon": "📝"},
                    {"id": "seo", "name": "SEO关键词", "count": 3, "icon": "🔎"},
                    {"id": "ppc", "name": "PPC广告", "count": 5, "icon": "💸"},
                    {"id": "review", "name": "Review管理", "count": 3, "icon": "⭐"},
                    {"id": "brand", "name": "Brand Store", "count": 3, "icon": "🏪"},
                    {"id": "dsp", "name": "DSP广告", "count": 2, "icon": "🎯"},
                    {"id": "external", "name": "站外引流", "count": 3, "icon": "🌐"},
                    {"id": "affiliate", "name": "联盟营销", "count": 2, "icon": "🤝"},
                    {"id": "matrix", "name": "品牌矩阵", "count": 1, "icon": "🔄"},
                ],
            },
            "shopifydtc": {
                "name": "Shopify DTC 品牌增长SOP",
                "icon": "🛍️",
                "total": 40,
                "categories": [
                    {"id": "brand", "name": "品牌战略", "count": 5, "icon": "🎯"},
                    {"id": "shopify", "name": "Shopify运营", "count": 6, "icon": "🏬"},
                    {"id": "meta", "name": "Meta广告", "count": 5, "icon": "📱"},
                    {"id": "google", "name": "Google广告", "count": 4, "icon": "🔍"},
                    {"id": "seo", "name": "SEO优化", "count": 4, "icon": "📈"},
                    {"id": "email", "name": "Email营销", "count": 4, "icon": "📧"},
                    {"id": "whatsapp", "name": "WhatsApp营销", "count": 3, "icon": "💬"},
                    {"id": "member", "name": "会员体系", "count": 3, "icon": "👑"},
                    {"id": "community", "name": "社区运营", "count": 3, "icon": "👥"},
                    {"id": "fulfillment", "name": "履约管理", "count": 3, "icon": "📦"},
                ],
            },
            "factory": {
                "name": "AI工厂出海SOP",
                "icon": "🏭",
                "total": 17,
                "categories": [
                    {"id": "market", "name": "市场调研", "count": 3, "icon": "🔍"},
                    {"id": "product", "name": "产品开发", "count": 3, "icon": "🔧"},
                    {"id": "supply", "name": "供应链", "count": 3, "icon": "🚚"},
                    {"id": "sales", "name": "销售渠道", "count": 4, "icon": "💼"},
                    {"id": "brand", "name": "品牌建设", "count": 2, "icon": "🏷️"},
                    {"id": "compliance", "name": "合规认证", "count": 2, "icon": "✅"},
                ],
            },
        }
        return {"success": True, "systems": systems}

    # ============================================================
    # Knowledge Base File Upload API
    # ============================================================

    _UPLOAD_DIR = Path(__file__).parent.parent / "knowledge" / "uploads"
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    @app.post("/api/knowledge/upload")
    async def knowledge_upload(request: Request):
        """接收前端上传的文件，保存到 knowledge/uploads 目录"""
        import shutil
        form = await request.form()
        file = form.get("file")
        target_kb = (form.get("target_kb") or "默认知识库").strip()
        
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")

        content = await file.read()
        safe_name = file.filename.replace("/", "_").replace("\\", "_").replace("..", "")
        
        # 防止同名覆盖
        dest = _UPLOAD_DIR / safe_name
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            dest = _UPLOAD_DIR / f"{stem}_{int(datetime.now().timestamp())}{suffix}"

        with open(dest, "wb") as f:
            f.write(content)

        logger.info(f"[Knowledge] Uploaded: {dest.name} -> {target_kb} ({len(content)} bytes)")

        return {
            "success": True,
            "file_name": dest.name,
            "size": len(content),
            "target_kb": target_kb,
            "path": str(dest.relative_to(Path(__file__).parent.parent)),
        }

    @app.get("/api/knowledge/files")
    def knowledge_list_files():
        """列出已上传的知识库文件"""
        files = []
        for p in sorted(_UPLOAD_DIR.rglob("*")):
            if p.is_file() and "__pycache__" not in str(p):
                stat = p.stat()
                files.append({
                    "name": p.name,
                    "relative_path": str(p.relative_to(_UPLOAD_DIR)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return {"success": True, "files": files, "total": len(files)}

    # ============================================================
    # Knowledge Link Parsing API (网页 / 飞书文档)
    # ============================================================

    _KB_LINKS_DIR = Path(__file__).parent.parent / "knowledge" / "links"
    _KB_LINKS_DIR.mkdir(parents=True, exist_ok=True)
    _KB_LINKS_FILE = _KB_LINKS_DIR / "links.json"

    def _load_kb_links() -> list:
        """加载知识库链接列表"""
        if _KB_LINKS_FILE.exists():
            try:
                return json.loads(_KB_LINKS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_kb_links(links: list):
        """保存知识库链接列表"""
        _KB_LINKS_FILE.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")

    @app.post("/api/knowledge/link/add")
    async def knowledge_add_link(req: KnowledgeLinkRequest):
        """添加网页/飞书文档链接到知识库，自动解析内容"""
        import httpx
        links = _load_kb_links()

        # 检查重复
        for lk in links:
            if lk.get("url") == req.url:
                return {"success": False, "message": "该链接已存在", "link": lk}

        # 解析链接内容
        parsed_title = req.url
        parsed_content = ""
        parse_status = "pending"

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
                resp = await client.get(req.url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                })
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" in content_type:
                        # 简单提取标题和文本
                        html = resp.text
                        import re
                        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                        if title_match:
                            parsed_title = title_match.group(1).strip()[:200]

                        # 移除 script/style 标签，提取纯文本
                        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.IGNORECASE | re.DOTALL)
                        text = re.sub(r'<[^>]+>', ' ', text)
                        text = re.sub(r'\s+', ' ', text).strip()
                        parsed_content = text[:5000]  # 最多5000字符
                        parse_status = "parsed"
                    elif "application/json" in content_type:
                        parsed_content = resp.text[:5000]
                        parse_status = "parsed"
                    else:
                        parse_status = "fetched"
                else:
                    parse_status = f"http_{resp.status_code}"
        except Exception as e:
            parse_status = f"error: {str(e)[:100]}"

        # 判断链接类型显示
        display_type = req.link_type
        if "feishu" in req.url.lower():
            display_type = "feishu"

        new_link = {
            "id": str(uuid.uuid4())[:8],
            "url": req.url,
            "title": parsed_title,
            "content_preview": parsed_content[:500],
            "content_length": len(parsed_content),
            "type": display_type,
            "kb_name": req.kb_name,
            "parse_status": parse_status,
            "added_at": datetime.now().isoformat(),
        }
        links.append(new_link)
        _save_kb_links(links)

        logger.info(f"[Knowledge] Link added: {req.url} -> {req.kb_name} (status: {parse_status})")
        return {"success": True, "message": "链接已添加并解析", "link": new_link, "total": len(links)}

    @app.get("/api/knowledge/links")
    def knowledge_list_links():
        """列出所有知识库链接"""
        links = _load_kb_links()
        return {"success": True, "links": links, "total": len(links)}

    @app.delete("/api/knowledge/link/{link_id}")
    def knowledge_delete_link(link_id: str):
        """删除知识库链接"""
        links = _load_kb_links()
        original_len = len(links)
        links = [lk for lk in links if lk.get("id") != link_id]
        _save_kb_links(links)
        deleted = original_len - len(links)
        return {"success": deleted > 0, "deleted": deleted}

    @app.post("/api/knowledge/link/parse-again/{link_id}")
    async def knowledge_reparse_link(link_id: str):
        """重新解析知识库链接内容"""
        import httpx, re
        links = _load_kb_links()
        target = None
        for lk in links:
            if lk.get("id") == link_id:
                target = lk
                break
        if not target:
            raise HTTPException(status_code=404, detail="链接不存在")

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
                resp = await client.get(target["url"], headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                })
                if resp.status_code == 200:
                    html = resp.text
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                    if title_match:
                        target["title"] = title_match.group(1).strip()[:200]
                    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.IGNORECASE | re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    target["content_preview"] = text[:500]
                    target["content_length"] = len(text)
                    target["parse_status"] = "parsed"
                else:
                    target["parse_status"] = f"http_{resp.status_code}"
        except Exception as e:
            target["parse_status"] = f"error: {str(e)[:100]}"

        _save_kb_links(links)
        return {"success": True, "link": target}

    @app.post("/api/knowledge/link/batch-add-agents")
    def knowledge_batch_add_to_agents(req: BatchAddLinkToAgentsRequest):
        """将知识库链接一键分配给多个/全部智能体"""
        agents_dir = Path(__file__).parent.parent / "agents"
        updated = []
        skipped = []

        # 构建 agent_id -> path 的索引（agents 目录下所有 .toml）
        all_agent_map = {}
        for p in sorted(agents_dir.rglob("*.toml")):
            agent_id = p.stem
            if agent_id == "registry":
                continue
            all_agent_map[agent_id] = p

        # 确定目标智能体列表
        if req.agent_ids:
            target_agents = []
            for aid in req.agent_ids:
                if aid in all_agent_map:
                    target_agents.append({"id": aid, "path": all_agent_map[aid]})
                else:
                    skipped.append({"id": aid, "reason": "配置文件不存在"})
        else:
            # 全部智能体
            target_agents = [{"id": aid, "path": p} for aid, p in all_agent_map.items()]

        # 验证链接
        links = _load_kb_links()
        target_link = None
        for lk in links:
            if lk.get("url") == req.url:
                target_link = lk
                break
        if not target_link:
            raise HTTPException(status_code=404, detail="链接未找到，请先添加链接到知识库")

        # 为每个智能体添加知识库引用
        for agent in target_agents:
            try:
                content = agent["path"].read_text(encoding="utf-8")

                # 检查是否已有 knowledge_sources 配置
                if "[agent.knowledge_sources]" in content:
                    # 已有配置，追加链接
                    link_entry = f'\n[[agent.knowledge_sources.links]]\nurl = "{req.url}"\ntype = "{req.link_type}"\ntitle = "{target_link.get("title", req.url)}"'
                    content = content.rstrip() + link_entry + "\n"
                else:
                    # 新增 knowledge_sources 配置段
                    kb_section = f'''
[agent.knowledge_sources]
# 知识库链接 - 自动添加
[[agent.knowledge_sources.links]]
url = "{req.url}"
type = "{req.link_type}"
title = "{target_link.get("title", req.url)}"
'''
                    content = content.rstrip() + kb_section + "\n"

                agent["path"].write_text(content, encoding="utf-8")
                updated.append({"id": agent["id"], "name": agent["id"]})
            except Exception as e:
                skipped.append({"id": agent["id"], "reason": str(e)})

        logger.info(f"[Knowledge] Batch add link to agents: {len(updated)} updated, {len(skipped)} skipped")
        return {
            "success": True,
            "message": f"已为 {len(updated)} 个智能体添加知识库链接",
            "updated_count": len(updated),
            "skipped_count": len(skipped),
            "updated": updated,
            "skipped": skipped,
        }

    @app.get("/api/knowledge/link/agents-status/{link_id}")
    def knowledge_link_agents_status(link_id: str):
        """查询某条链接在哪些智能体中已配置"""
        links = _load_kb_links()
        target_url = None
        for lk in links:
            if lk.get("id") == link_id:
                target_url = lk.get("url")
                break
        if not target_url:
            raise HTTPException(status_code=404, detail="链接不存在")

        agents_dir = Path(__file__).parent.parent / "agents"
        configured = []
        not_configured = []

        for p in sorted(agents_dir.rglob("*.toml")):
            agent_id = p.stem
            if agent_id == "registry":
                continue
            content = p.read_text(encoding="utf-8")
            if target_url in content:
                configured.append(agent_id)
            else:
                not_configured.append(agent_id)

        return {
            "success": True,
            "link_id": link_id,
            "url": target_url,
            "configured_count": len(configured),
            "not_configured_count": len(not_configured),
            "configured": configured,
            "not_configured": not_configured,
        }

    @app.get("/api/knowledge/links-stats")
    def knowledge_links_stats():
        """知识库链接统计信息"""
        links = _load_kb_links()
        agents_dir = Path(__file__).parent.parent / "agents"
        total_agents = sum(1 for p in agents_dir.rglob("*.toml") if p.stem != "registry")

        web_count = sum(1 for l in links if l.get("type") == "web")
        feishu_count = sum(1 for l in links if l.get("type") == "feishu")
        parsed_count = sum(1 for l in links if l.get("parse_status") == "parsed")

        return {
            "success": True,
            "total_links": len(links),
            "web_links": web_count,
            "feishu_links": feishu_count,
            "parsed_links": parsed_count,
            "total_agents": total_agents,
        }

    # ============================================================
    # Auth APIs - 用户认证与企业管理系统
    # ============================================================

    from .auth import (
        get_auth_service,
        RegisterRequest, EnterpriseRegisterRequest, LoginRequest,
        UserUpdateRequest, PasswordChangeRequest,
    )
    from fastapi import Depends
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    auth_service = get_auth_service()
    security = HTTPBearer(auto_error=False)

    async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """从请求中提取当前登录用户"""
        if not credentials:
            raise HTTPException(status_code=401, detail="请先登录")
        user = auth_service.verify_access(credentials.credentials)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        return user

    async def get_current_admin(user: dict = Depends(get_current_user)):
        """验证管理员权限"""
        if user["role"] not in ("admin", "enterprise_admin"):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user

    # ---- 注册 ----

    @app.post("/api/auth/register")
    async def register(req: RegisterRequest):
        """用户注册"""
        result = auth_service.register_user(req)
        if result["success"]:
            return result
        raise HTTPException(status_code=400, detail=result["error"])

    @app.post("/api/auth/register/enterprise")
    async def register_enterprise(req: EnterpriseRegisterRequest):
        """企业注册"""
        result = auth_service.register_enterprise(req)
        if result["success"]:
            return result
        raise HTTPException(status_code=400, detail=result["error"])

    # ---- 登录 ----

    @app.post("/api/auth/login")
    async def login(req: LoginRequest):
        """用户登录"""
        result = auth_service.login(req)
        if result["success"]:
            return result
        raise HTTPException(status_code=401, detail=result["error"])

    # ---- Token 刷新 ----

    @app.post("/api/auth/refresh")
    async def refresh_token(request: Request):
        """刷新访问 Token"""
        body = await request.json()
        refresh = body.get("refresh_token", "")
        if not refresh:
            raise HTTPException(status_code=400, detail="缺少 refresh_token")
        result = auth_service.refresh_token(refresh)
        if result["success"]:
            return result
        raise HTTPException(status_code=401, detail=result["error"])

    # ---- 退出 ----

    @app.post("/api/auth/logout")
    async def logout(user: dict = Depends(get_current_user)):
        """退出登录"""
        auth_service.logout(user["id"])
        return {"success": True, "message": "已退出登录"}

    # ---- 用户信息 ----

    @app.get("/api/auth/me")
    async def get_me(user: dict = Depends(get_current_user)):
        """获取当前用户信息"""
        return {"success": True, "user": user}

    @app.put("/api/auth/me")
    async def update_me(req: UserUpdateRequest, user: dict = Depends(get_current_user)):
        """更新当前用户信息"""
        updates = {}
        if req.display_name:
            updates["display_name"] = req.display_name
        if req.avatar:
            updates["avatar"] = req.avatar
        updated = auth_service.update_user(user["id"], updates)
        if updated:
            return {"success": True, "user": updated}
        raise HTTPException(status_code=404, detail="用户不存在")

    @app.put("/api/auth/me/password")
    async def change_my_password(req: PasswordChangeRequest, user: dict = Depends(get_current_user)):
        """修改当前用户密码"""
        result = auth_service.change_password(user["id"], req.old_password, req.new_password)
        if result["success"]:
            return result
        raise HTTPException(status_code=400, detail=result["error"])

    # ---- 企业管理 ----

    @app.get("/api/auth/enterprise")
    async def get_my_enterprise(user: dict = Depends(get_current_user)):
        """获取当前用户所在企业信息"""
        ent_id = user.get("enterprise_id")
        if not ent_id:
            raise HTTPException(status_code=404, detail="您不属于任何企业")
        enterprise = auth_service.get_enterprise(ent_id)
        if not enterprise:
            raise HTTPException(status_code=404, detail="企业不存在")
        return {"success": True, "enterprise": enterprise}

    @app.get("/api/auth/enterprise/users")
    async def list_enterprise_users(user: dict = Depends(get_current_user)):
        """获取企业用户列表"""
        ent_id = user.get("enterprise_id")
        if not ent_id:
            raise HTTPException(status_code=404, detail="您不属于任何企业")
        users = auth_service.get_enterprise_users(ent_id)
        return {"success": True, "users": users, "total": len(users)}

    @app.post("/api/auth/enterprise/users")
    async def add_enterprise_user(
        request: Request,
        user: dict = Depends(get_current_user),
    ):
        """企业管理员添加用户"""
        if user["role"] not in ("admin", "enterprise_admin"):
            raise HTTPException(status_code=403, detail="需要企业管理员权限")
        body = await request.json()
        ent_id = user.get("enterprise_id")
        if not ent_id:
            raise HTTPException(status_code=400, detail="未关联企业")
        result = auth_service.add_enterprise_user(
            ent_id=ent_id,
            email=body.get("email", ""),
            username=body.get("username", ""),
            password=body.get("password", ""),
            role=body.get("role", "enterprise_user"),
        )
        if result["success"]:
            return result
        raise HTTPException(status_code=400, detail=result["error"])

    # ---- 管理员接口 ----

    @app.get("/api/auth/admin/users")
    async def admin_list_users(user: dict = Depends(get_current_admin)):
        """管理员查看所有用户"""
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="需要超级管理员权限")
        users = auth_service.get_all_users()
        return {"success": True, "users": users, "total": len(users)}

    @app.get("/api/auth/admin/enterprises")
    async def admin_list_enterprises(user: dict = Depends(get_current_admin)):
        """管理员查看所有企业"""
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="需要超级管理员权限")
        enterprises = auth_service.get_all_enterprises()
        return {"success": True, "enterprises": enterprises, "total": len(enterprises)}

    logger.info("🔐 Auth API routes registered (register/login/enterprise management)")

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


# ============================================================
# SOP 辅助函数
# ============================================================

_SOP_CATEGORY_PROMPTS = {
    "tiktokshop_product": "你是 TikTok Shop 选品专家。分析市场趋势，找出高潜力产品。",
    "tiktokshop_content": "你是 TikTok 短视频内容专家。创作高转化率的短视频脚本和内容策略。",
    "tiktokshop_influencer": "你是 TikTok 达人合作专家。制定达人筛选、合作和效果追踪策略。",
    "tiktokshop_live": "你是 TikTok 直播运营专家。设计直播脚本、互动策略和转化方案。",
    "tiktokshop_ads": "你是 TikTok 广告投放专家。优化广告创意、受众定位和ROI。",
    "tiktokshop_private": "你是私域运营专家。设计私域流量池搭建和用户运营策略。",
    "tiktokshop_affiliate": "你是联盟营销专家。制定联盟计划和佣金策略。",
    "tiktokshop_growth": "你是 GMV 增长策略专家。设计增长飞轮和规模化策略。",
    "amazonbrand_product": "你是 Amazon 选品专家。通过数据分析找出高利润蓝海品类。",
    "amazonbrand_listing": "你是 Amazon Listing 优化专家。优化标题、五点、A+内容和图片。",
    "amazonbrand_seo": "你是 Amazon SEO 专家。研究高转化关键词和搜索排名策略。",
    "amazonbrand_ppc": "你是 Amazon PPC 广告专家。优化广告架构、竞价和ACOS。",
    "amazonbrand_review": "你是 Amazon Review 管理专家。制定评价获取和维护策略。",
    "amazonbrand_brand": "你是 Amazon Brand Store 专家。设计品牌旗舰店和品牌体验。",
    "amazonbrand_dsp": "你是 Amazon DSP 广告专家。制定程序化广告和受众策略。",
    "amazonbrand_external": "你是站外引流专家。设计多渠道引流到 Amazon 的策略。",
    "amazonbrand_affiliate": "你是 Amazon 联盟营销专家。制定联盟计划和达人合作策略。",
    "amazonbrand_matrix": "你是品牌矩阵策略专家。设计多品牌多店铺运营矩阵。",
    "shopifydtc_brand": "你是 DTC 品牌战略专家。制定品牌定位、故事和价值主张。",
    "shopifydtc_shopify": "你是 Shopify 运营专家。优化店铺设计、转化率和用户体验。",
    "shopifydtc_meta": "你是 Meta 广告专家。优化 Facebook/Instagram 广告投放策略。",
    "shopifydtc_google": "你是 Google 广告专家。优化搜索、购物和展示广告策略。",
    "shopifydtc_seo": "你是 SEO 优化专家。制定技术SEO、内容SEO和外链策略。",
    "shopifydtc_email": "你是 Email 营销专家。设计自动化邮件序列和细分策略。",
    "shopifydtc_whatsapp": "你是 WhatsApp 营销专家。设计消息模板和自动化流程。",
    "shopifydtc_member": "你是会员体系专家。设计会员等级、权益和忠诚度计划。",
    "shopifydtc_community": "你是社区运营专家。设计社区建设、内容和互动策略。",
    "shopifydtc_fulfillment": "你是履约管理专家。优化物流、仓储和配送策略。",
    "factory_market": "你是OEM/ODM市场调研专家。分析海外市场需求和竞争格局。",
    "factory_product": "你是产品开发专家。从OEM转型自主品牌的产品策略。",
    "factory_supply": "你是供应链管理专家。优化跨境供应链和物流体系。",
    "factory_sales": "你是销售渠道专家。制定B2B+B2C多渠道销售策略。",
    "factory_brand": "你是品牌建设专家。帮助工厂建立自主品牌和品牌出海。",
    "factory_compliance": "你是合规认证专家。指导CE/FDA/FCC等国际认证流程。",
}

def _build_sop_system_prompt(category: str, task_name: str) -> str:
    """构建 SOP 系统提示词"""
    key = f"{category}_{task_name.split('_')[0]}" if "_" in task_name else f"{category}_{task_name}"
    base_prompt = _SOP_CATEGORY_PROMPTS.get(key, "")
    if not base_prompt:
        # 模糊匹配
        for k, v in _SOP_CATEGORY_PROMPTS.items():
            if k.startswith(category):
                base_prompt = v
                break

    return f"""{base_prompt or '你是跨境电商品牌出海专家。'}

请提供专业、详细、可执行的方案。回复应包含：
1. 核心策略和关键步骤
2. 具体执行方案和时间节点
3. 关键指标(KPI)和预期效果
4. 风险提示和应对方案
5. 所需资源和工具建议

用中文回答，专业但易懂。"""

def _build_sop_user_prompt(category: str, task_name: str, input_data: dict) -> str:
    """构建 SOP 用户提示词"""
    parts = [f"请为我执行以下跨境电商任务：\n\n**系统**: {category}\n**任务**: {task_name}"]

    if input_data:
        parts.append("\n**输入参数**:")
        for k, v in input_data.items():
            parts.append(f"- {k}: {v}")

    parts.append("\n请提供详细的执行方案和分析结果。")
    return "\n".join(parts)

async def _execute_sop_sync(engine, system_prompt: str, user_prompt: str, task_name: str) -> dict:
    """同步执行 SOP 任务"""
    llm = engine.runtime.llm_client
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = await llm.chat(
        provider="ollama",
        model="",
        messages=messages,
        temperature=0.7,
        max_tokens=4096,
    )
    return {
        "success": True,
        "task_name": task_name,
        "response": response.content,
        "model": response.model,
        "tokens_used": response.tokens_used,
    }

async def _execute_sop_async(engine, system_prompt: str, user_prompt: str, task_name: str):
    """异步执行 SOP 任务（后台）"""
    try:
        result = await _execute_sop_sync(engine, system_prompt, user_prompt, task_name)
        logger.info(f"[SOP] Async task completed: {task_name}, tokens={result.get('tokens_used', 0)}")
    except Exception as e:
        logger.error(f"[SOP] Async task failed: {task_name}, error={e}")


def run_server_v2(engine, host: str = "0.0.0.0", port: int = 8080):
    """启动 HTTP 服务器（v2）"""
    app = create_app_v2(engine, host, port)
    logger.info(f"🚀 Starting OpenClaw Unified Engine API v2 on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
