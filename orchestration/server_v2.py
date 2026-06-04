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
        import httpx
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "connected": True,
                        "models_count": len(data.get("models", [])),
                        "models": [m.get("name") for m in data.get("models", [])],
                    }
        except Exception:
            pass
        return {"connected": False, "models_count": 0, "models": []}

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
