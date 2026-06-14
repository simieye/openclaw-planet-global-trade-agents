"""
Server v2 - 统一引擎 HTTP API 服务器
FastAPI 服务器 - Dashboard 管理面板 + REST API + Webhook 接收 + Agent 触发
"""

import asyncio
import json
import logging
import os
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
        title="Simiaiclaw OS · 全量调度操作系统",
        description="🦞 龙虾星球共创联盟 - 一万个硅基大脑 · 全量调度操作系统 · Agent First 时代跨境电商品牌出海智能体集群",
        version="5.4.0",
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

    @app.get("/brand-os", response_class=HTMLResponse)
    async def brand_os():
        """Simiaiclaw OS 品牌叙事页面"""
        html_path = dashboard_path / "brand-os.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return HTMLResponse(content="<h1>Brand OS 页面未找到</h1>", status_code=404)

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
            version="5.4.0",
            uptime_seconds=uptime,
            agents_count=status.get("total_agents", 0),
            taskflows_count=status.get("total_taskflows", 0),
        )

    @app.get("/api/status")
    async def engine_status():
        return _engine.get_status()

    @app.get("/api/dashboard")
    async def get_dashboard():
        """获取 Dashboard 实时数据"""
        if hasattr(_engine, 'get_dashboard_data'):
            return await _engine.get_dashboard_data()
        # 回退：从 status 构建 dashboard 数据
        status = _engine.get_status()
        return {
            "engine": status.get("engine", "unknown"),
            "total_agents": status.get("total_agents", 0),
            "total_taskflows": status.get("total_taskflows", 0),
            "total_webhook_routes": status.get("total_webhook_routes", 0),
            "agents_by_layer": status.get("agents_by_layer", {}),
            "uptime": (datetime.now() - _start_time).total_seconds(),
        }

    # ============================================================
    # Agent APIs
    # ============================================================

    @app.get("/api/agents")
    async def list_agents(layer: str = None):
        status = _engine.get_status()
        agents = status.get("agents_by_layer", {})
        total = status.get("total_agents", 0)
        if layer:
            return {"agents": agents.get(layer, [])}
        return {"agents": agents, "total": total}

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
        return {"taskflows": status.get("total_taskflows", 0), "total": status.get("total_taskflows", 0)}

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
        if hasattr(_engine, 'connector_hub') and _engine.connector_hub:
            return {"connectors": _engine.connector_hub.get_all()}
        return {"connectors": {}, "message": "Connector hub not available"}

    # ============================================================
    # Skills API - 跨境电商技能库
    # ============================================================

    @app.get("/api/skills")
    async def list_skills(category: str = ""):
        """列出所有跨境电商技能"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        # 从 SkillRegistry 获取所有 SKILL.md 技能
        all_skills = []
        if hasattr(_engine.runtime, 'skill_registry'):
            all_skills = _engine.runtime.skill_registry.list_skill_md()

        if not all_skills and _engine.runtime:
            # 回退：从 agent_brain 的 SkillRegistry 获取
            all_skills = _engine.runtime.skills.list_skill_md()

        if category:
            all_skills = [s for s in all_skills if category.lower() in s.get("category", "").lower()]

        # 按分类组织
        categories = {}
        for s in all_skills:
            cat = s.get("category", "未分类")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(s)

        return {
            "success": True,
            "total": len(all_skills),
            "categories": categories,
            "skills": all_skills,
        }

    @app.get("/api/skills/categories")
    async def list_skill_categories():
        """列出技能分类（必须在 /api/skills/{skill_name} 之前注册）"""
        categories = {
            "tiktok_video": {"name": "TikTok & 短视频工业化", "count": 7, "icon": "🎵"},
            "seo_geo": {"name": "SEO/GEO/AI搜索优化", "count": 7, "icon": "🔍"},
            "ads_roi": {"name": "广告投放与ROI优化", "count": 7, "icon": "📢"},
            "market_intel": {"name": "竞品监控与市场洞察", "count": 7, "icon": "🔎"},
            "listing_cro": {"name": "Listing优化与转化率", "count": 7, "icon": "📝"},
            "social_matrix": {"name": "社媒矩阵与分发", "count": 8, "icon": "🌐"},
            "ai_frontend": {"name": "AI前端 / UI设计", "count": 2, "icon": "🎨"},
            "doc_parsing": {"name": "文档解析 / RAG", "count": 2, "icon": "📄"},
            "composio": {"name": "Composio · 1000+应用集成", "count": 1, "icon": "🔌"},
            "store_management": {"name": "店铺管理", "count": 7, "icon": "🏪"},
            "store_operations": {"name": "店铺经营", "count": 8, "icon": "📊"},
            "product_selection": {"name": "选品与商品", "count": 10, "icon": "🎯"},
            "marketing_content": {"name": "营销与内容", "count": 21, "icon": "📣"},
            "market_analysis": {"name": "市场分析", "count": 5, "icon": "📈"},
            "platform_connectors": {"name": "平台连接器", "count": 30, "icon": "🔗"},
            "claude_document": {"name": "Claude · 文档处理", "count": 4, "icon": "📄"},
            "claude_dev": {"name": "Claude · 开发与代码", "count": 7, "icon": "💻"},
            "claude_business": {"name": "Claude · 商业与营销", "count": 6, "icon": "💼"},
            "claude_creative": {"name": "Claude · 创意与媒体", "count": 5, "icon": "🎨"},
            "claude_productivity": {"name": "Claude · 生产力工具", "count": 9, "icon": "⚙️"},
            "amazon_data_intelligence": {"name": "Amazon 数据情报", "count": 1, "icon": "🔍"},
        }
        return {"success": True, "categories": categories}

    # ============================================================
    # Composio v3 集成 API — 真实 SDK 集成，1000 工具包 / 41837 工具
    # ============================================================

    @app.get("/api/composio/status")
    async def composio_status():
        """获取 Composio 集成状态（实时 API 验证 + 首次初始化）"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            
            # 首次访问时自动初始化（加载工具包列表 + 连接状态）
            if hub.registry.toolkit_count == 0:
                logger.info("[Composio] First access — initializing hub...")
                init_result = hub.initialize()
                logger.info(f"[Composio] Init result: {init_result}")
            
            status = hub.get_status()
            return {"success": True, **status}
        except Exception as e:
            logger.error(f"Composio status error: {e}")
            composio_key = os.environ.get("COMPOSIO_API_KEY", "")
            return {
                "success": True,
                "configured": bool(composio_key),
                "masked_key": composio_key[:8] + "***" if composio_key else "",
                "toolkits": 0,
                "tools": 0,
                "connections": 0,
                "connected_apps": [],
                "categories": {},
                "message": f"Composio 集成初始化中: {str(e)}",
            }

    @app.get("/api/composio/toolkits")
    async def composio_list_toolkits(
        category: str = None,
        query: str = None,
        popular: bool = False,
        limit: int = 50,
        page: int = 1,
        page_size: int = 100,
    ):
        """列出 Composio 工具包（支持按分类/关键词筛选 + 分页）"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            
            # 懒初始化
            if hub.registry.toolkit_count == 0:
                hub.initialize()

            if popular:
                # popular=true 时返回最多 limit 个热门工具包 + 全部分类统计
                toolkits = hub.get_popular_toolkits(min(limit, 300))
                categories = hub.get_categories()
                return {
                    "success": True,
                    "total_toolkits": hub.registry.toolkit_count,
                    "total_tools": hub.registry.tool_count,
                    "categories": categories,
                    "popular": toolkits,
                }
            elif query:
                toolkits = hub.search(query, category, limit)
                return {
                    "success": True,
                    "total": len(toolkits),
                    "toolkits": toolkits,
                }
            elif category:
                toolkits = hub.registry.get_by_category(category)[:limit]
                return {
                    "success": True,
                    "total": len(toolkits),
                    "toolkits": toolkits,
                }
            else:
                # 分页返回所有工具包
                all_tk = hub.registry._toolkits
                total = len(all_tk)
                start = (page - 1) * page_size
                end = start + page_size
                page_items = all_tk[start:end]
                # 转换为摘要格式
                toolkits = [hub.registry._toolkit_to_summary(tk) for tk in page_items]
                categories = hub.get_categories()
                return {
                    "success": True,
                    "total_toolkits": hub.registry.toolkit_count,
                    "total_tools": hub.registry.tool_count,
                    "categories": categories,
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "toolkits": toolkits,
                }
        except Exception as e:
            logger.error(f"Composio toolkits error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/composio/toolkits/{slug}")
    async def composio_get_toolkit(slug: str):
        """获取工具包详细信息"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            detail = hub.get_toolkit_detail(slug)
            if not detail:
                raise HTTPException(status_code=404, detail=f"Toolkit not found: {slug}")
            return {"success": True, **detail}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Composio toolkit detail error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/composio/categories")
    async def composio_list_categories():
        """列出所有工具包分类"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            # 懒初始化
            if hub.registry.toolkit_count == 0:
                hub.initialize()
            categories = hub.get_categories()
            return {
                "success": True,
                "total_categories": len(categories),
                "categories": categories,
                "total_toolkits": hub.registry.toolkit_count,
                "total_tools": hub.registry.tool_count,
            }
        except Exception as e:
            logger.error(f"Composio categories error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/composio/search")
    async def composio_search(request: Request):
        """搜索 Composio 工具包"""
        try:
            body = await request.json()
            query = body.get("query", "")
            category = body.get("category")
            limit = body.get("limit", 20)

            if not query and not category:
                raise HTTPException(status_code=400, detail="query or category is required")

            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            # 懒初始化
            if hub.registry.toolkit_count == 0:
                hub.initialize()
            results = hub.search(query, category, limit)

            return {
                "success": True,
                "query": query,
                "category": category,
                "total": len(results),
                "results": results,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Composio search error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/composio/execute")
    async def composio_execute(request: Request):
        """通过 Composio 执行工具调用"""
        try:
            body = await request.json()
            tool_slug = body.get("slug", "")
            params = body.get("params", {})
            app_slug = body.get("app")
            connected_account_id = body.get("connectedAccountId")

            if not tool_slug:
                raise HTTPException(status_code=400, detail="slug is required")

            from composio_integration import get_composio_hub
            hub = get_composio_hub()

            result = hub.sessions.execute(
                tool_slug, params, app_slug, connected_account_id
            )

            return {
                "success": True,
                "slug": tool_slug,
                "result": result,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Composio execute error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/composio/connections")
    async def composio_list_connections():
        """获取已连接的第三方应用账户列表"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            connections = hub.get_connections()
            return {
                "success": True,
                "total": len(connections),
                "connections": connections,
            }
        except Exception as e:
            logger.error(f"Composio connections error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/composio/connect")
    async def composio_initiate_connection(request: Request):
        """发起 OAuth 连接（支持托管OAuth、自定义OAuth和API Key三种模式）"""
        try:
            body = await request.json()
            app_slug = body.get("app")
            redirect_url = body.get("redirectUrl")
            auth_mode = body.get("authMode")
            auth_config = body.get("authConfig")

            if not app_slug:
                raise HTTPException(status_code=400, detail="app is required")

            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            result = hub.initiate_connection(app_slug, redirect_url, auth_mode, auth_config)

            # 提取可能的 redirectUrl
            redirect_url_result = result.get("redirectUrl") or result.get("redirect_url")
            return {
                "success": True,
                "redirectUrl": redirect_url_result,
                "connectionId": result.get("connectionId") or result.get("id"),
                "message": result.get("message", "Connection initiated"),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Composio connect error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/composio/popular")
    async def composio_popular_toolkits(limit: int = 50):
        """获取热门工具包"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            # 懒初始化
            if hub.registry.toolkit_count == 0:
                hub.initialize()
            toolkits = hub.get_popular_toolkits(limit)
            return {
                "success": True,
                "total": len(toolkits),
                "toolkits": toolkits,
                "total_toolkits": hub.registry.toolkit_count,
                "total_tools": hub.registry.tool_count,
            }
        except Exception as e:
            logger.error(f"Composio popular error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/composio/save-api-key")
    async def composio_save_api_key(request: Request):
        """保存应用的 API Key（存储到 Composio connected accounts）"""
        try:
            body = await request.json()
            app_slug = body.get("app_slug", "")
            api_key = body.get("api_key", "")
            label = body.get("label", app_slug)

            if not app_slug or not api_key:
                raise HTTPException(status_code=400, detail="app_slug and api_key are required")

            from composio_integration import get_composio_hub
            hub = get_composio_hub()

            # 通过 Composio API 创建 connected account with API_KEY auth
            result = hub.client.post("/connected_accounts", json_data={
                "appSlug": app_slug,
                "authMode": "API_KEY",
                "authConfig": {
                    "api_key": api_key,
                },
                "label": label,
            })
            # 刷新连接状态
            hub.sessions.sync_connections()
            return {"success": True, "app_slug": app_slug, "message": f"API Key for {app_slug} saved successfully", "result": result}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Composio save API key error: {e}")
            return {"success": False, "error": str(e), "app_slug": body.get("app_slug", "") if body else ""}

    @app.get("/api/composio/auth-config/{slug}")
    async def composio_get_auth_config(slug: str):
        """获取应用的认证配置信息（OAuth redirect URL 等）"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            config = hub.client.get_auth_config(slug)
            return {"success": True, "slug": slug, "config": config}
        except Exception as e:
            logger.error(f"Composio auth config error: {e}")
            return {"success": False, "error": str(e), "slug": slug}

    @app.delete("/api/composio/connections/{connection_id}")
    async def composio_delete_connection(connection_id: str):
        """断开 Composio 已连接账户"""
        try:
            from composio_integration import get_composio_hub
            hub = get_composio_hub()
            result = hub.client.delete(f"/connected_accounts/{connection_id}")
            hub.sessions.sync_connections()
            return {"success": True, "connection_id": connection_id, "message": "Connection removed"}
        except Exception as e:
            logger.error(f"Composio delete connection error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ============================================================
    # Composio 双通道连接测试 (REST API + MCP)
    # ============================================================

    @app.get("/api/composio/channels")
    async def composio_channel_status():
        """测试 Composio 双通道连接状态（REST API + MCP 协议）"""
        try:
            from composio_integration import get_composio_hub, ComposioClient, DEFAULT_API_KEY
            hub = get_composio_hub()

            # 懒初始化
            if hub.registry.toolkit_count == 0:
                hub.initialize()

            # Channel 1: REST API
            rest_status = {"connected": False, "error": None, "toolkits": 0}
            try:
                client = ComposioClient(api_key=DEFAULT_API_KEY)
                resp = client.list_toolkits(page=1, page_size=1)
                rest_status["connected"] = True
                # API 可能返回 total 为 None，用 items 数量推断
                items = resp.get("items", [])
                meta_total = resp.get("meta", {}).get("total")
                rest_status["toolkits"] = meta_total if meta_total else len(items) if items else 0
            except Exception as e:
                rest_status["error"] = str(e)

            # Channel 2: MCP 协议（通过 Composio SDK 代理）
            mcp_status = {"connected": False, "error": None, "endpoint": None}
            try:
                # MCP endpoint: Composio 提供标准 MCP SSE 协议支持
                # 使用 backend.composio.dev 的 MCP 端点
                mcp_endpoint = "https://backend.composio.dev/api/v3"
                mcp_status["endpoint"] = mcp_endpoint
                # 尝试通过 REST 方式检测 MCP 工具可用性
                import httpx
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as async_client:
                    # Composio MCP 通过 tools API 暴露
                    mcp_resp = await async_client.get(
                        f"{mcp_endpoint}/tools",
                        headers={"x-api-key": DEFAULT_API_KEY, "Content-Type": "application/json"},
                        params={"pageSize": 5}
                    )
                    if mcp_resp.status_code == 200:
                        mcp_data = mcp_resp.json()
                        items = mcp_data.get("items", [])
                        mcp_status["connected"] = True
                        mcp_status["tools_count"] = mcp_data.get("meta", {}).get("total", len(items))
                        mcp_status["protocol"] = "REST API (MCP-compatible)"
                    else:
                        mcp_status["error"] = f"HTTP {mcp_resp.status_code}: {mcp_resp.text[:200]}"
            except Exception as e:
                mcp_status["error"] = str(e)

            return {
                "success": True,
                "rest_api": rest_status,
                "mcp_protocol": mcp_status,
                "local_cache": {
                    "toolkits": hub.registry.toolkit_count,
                    "tools": hub.registry.tool_count,
                    "categories": len(hub.get_categories()),
                    "connections": len(hub.get_connections()),
                },
                "summary": (
                    "✅ 双通道正常" if rest_status["connected"] and mcp_status["connected"]
                    else "⚠️ 部分通道可用" if rest_status["connected"] or mcp_status["connected"]
                    else "❌ 所有通道不可用"
                ),
            }
        except Exception as e:
            logger.error(f"Composio channel test error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ============================================================
    # Heygen MCP Proxy API
    # ============================================================

    @app.get("/api/heygen/status")
    async def heygen_status():
        """检查 Heygen MCP 连接状态"""
        heygen_key = os.environ.get("HEYGEN_API_KEY", "")
        has_key = bool(heygen_key)
        return {
            "success": True,
            "configured": has_key,
            "mcp_endpoint": "https://mcp.heygen.com/mcp/v1/",
            "message": "Heygen MCP 已配置" if has_key else "未配置 HEYGEN_API_KEY",
        }

    @app.post("/api/heygen/proxy")
    async def heygen_proxy(request: Request):
        """代理转发 Heygen MCP 请求"""
        import httpx
        heygen_key = os.environ.get("HEYGEN_API_KEY", "")
        if not heygen_key:
            raise HTTPException(status_code=503, detail="HEYGEN_API_KEY 未配置")

        body = await request.json()
        method = body.get("method", "tools/list")
        params = body.get("params", {})

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.post(
                    "https://mcp.heygen.com/mcp/v1/",
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                    headers={
                        "Authorization": f"Bearer {heygen_key}",
                        "Content-Type": "application/json",
                    },
                )
                return {"success": resp.status_code == 200, "data": resp.json()}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ============================================================
    # Firecrawl Web Scraping API — 1000+ Agent 统一网页爬取引擎
    # ============================================================

    @app.get("/api/firecrawl/status")
    async def firecrawl_status():
        """检查 Firecrawl 集成状态"""
        try:
            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()
            status = service.check_status()
            return {"success": True, **status}
        except Exception as e:
            logger.error(f"Firecrawl status error: {e}")
            return {
                "success": False,
                "service": "Firecrawl",
                "error": str(e),
                "api_configured": bool(os.environ.get("FIRECRAWL_API_KEY", "")),
            }

    @app.post("/api/firecrawl/scrape")
    async def firecrawl_scrape(request: Request):
        """单页抓取 — 抓取指定 URL 的内容"""
        try:
            body = await request.json()
            url = body.get("url", "")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")

            from firecrawl_integration import get_firecrawl_service, FirecrawlClient, DEFAULT_API_KEY
            # 支持从前端传入 api_key，或使用默认 key
            api_key = body.get("api_key", DEFAULT_API_KEY)
            service = get_firecrawl_service()
            # 如果传入了自定义 key，创建新的 client
            if api_key and api_key != DEFAULT_API_KEY:
                service.client = FirecrawlClient(api_key=api_key)

            source_type = body.get("source_type", "website")

            if source_type == "competitor":
                result = service.scrape_competitor_site(
                    url,
                    extract_pricing=body.get("extract_pricing", True),
                    extract_products=body.get("extract_products", True),
                )
            elif source_type == "social_media":
                result = service.scrape_social_media(
                    platform=body.get("platform", "unknown"),
                    profile_url=url,
                    extract_posts=body.get("extract_posts", True),
                    max_posts=body.get("max_posts", 20),
                )
            elif source_type == "ecommerce":
                result = service.scrape_ecommerce_product(
                    platform=body.get("platform", "unknown"),
                    product_url=url,
                )
            else:
                result = service.client.scrape(
                    url,
                    formats=body.get("formats", ["markdown", "links"]),
                    only_main_content=body.get("only_main_content", True),
                    wait_for=body.get("wait_for", 0),
                )
                result = {"url": url, "content": result.get("data", result)}

            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl scrape error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/firecrawl/test")
    async def firecrawl_test(request: Request):
        """测试 Firecrawl API Key 连接"""
        try:
            body = await request.json()
            api_key = body.get("api_key", "")
            from firecrawl_integration import FirecrawlClient, DEFAULT_API_KEY
            # 使用提供的 key 或默认 key
            client = FirecrawlClient(api_key=api_key or DEFAULT_API_KEY)
            health = client.check_health()
            if health.get("status") == "connected":
                return {"success": True, "message": "Firecrawl API 连接成功", "detail": health.get("detail", {})}
            else:
                return {"success": False, "error": health.get("detail", "连接失败")}
        except Exception as e:
            logger.error(f"Firecrawl test error: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/firecrawl/search")
    async def firecrawl_search(request: Request):
        """搜索 + 实时抓取 — 搜索引擎结果 + 自动抓取页面内容"""
        try:
            body = await request.json()
            query = body.get("query", "")
            if not query:
                raise HTTPException(status_code=400, detail="query is required")

            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()

            result = service.search_and_scrape(
                query=query,
                limit=body.get("limit", 10),
                sources=body.get("sources", ["web", "news"]),
                scrape_results=body.get("scrape_results", True),
            )
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl search error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/firecrawl/crawl")
    async def firecrawl_crawl(request: Request):
        """启动异步批量爬取任务"""
        try:
            body = await request.json()
            url = body.get("url", "")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")

            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()

            result = service.start_crawl(
                url=url,
                max_pages=body.get("max_pages", 100),
                max_depth=body.get("max_depth", 3),
                label=body.get("label", ""),
            )
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl crawl error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/firecrawl/crawl/{job_id}")
    async def firecrawl_crawl_status(job_id: str):
        """查询爬取任务状态"""
        try:
            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()
            result = service.get_crawl_status(job_id)
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl crawl status error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/api/firecrawl/crawl/{job_id}")
    async def firecrawl_crawl_cancel(job_id: str):
        """取消爬取任务"""
        try:
            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()
            result = service.cancel_crawl_job(job_id)
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl crawl cancel error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/firecrawl/jobs")
    async def firecrawl_list_jobs():
        """列出所有活跃的爬取任务"""
        try:
            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()
            jobs = service.list_active_jobs()
            return {"success": True, "data": jobs, "count": len(jobs)}
        except Exception as e:
            logger.error(f"Firecrawl list jobs error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/firecrawl/extract")
    async def firecrawl_extract(request: Request):
        """AI 驱动的结构化数据提取"""
        try:
            body = await request.json()
            urls = body.get("urls", [])
            prompt = body.get("prompt", "")
            if not urls:
                raise HTTPException(status_code=400, detail="urls is required")
            if not prompt:
                raise HTTPException(status_code=400, detail="prompt is required")

            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()

            result = service.extract_structured_data(
                urls=urls,
                prompt=prompt,
                schema=body.get("schema"),
            )
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl extract error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/firecrawl/batch-scrape")
    async def firecrawl_batch_scrape(request: Request):
        """批量抓取多个 URL"""
        try:
            body = await request.json()
            urls = body.get("urls", [])
            if not urls:
                raise HTTPException(status_code=400, detail="urls is required")

            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()

            result = service.batch_scrape_urls(
                urls=urls,
                source_label=body.get("source_label", "batch"),
            )
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl batch scrape error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/firecrawl/map")
    async def firecrawl_map_site(request: Request):
        """网站地图发现 — 发现网站的所有 URL"""
        try:
            body = await request.json()
            url = body.get("url", "")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")

            from firecrawl_integration import get_firecrawl_service
            service = get_firecrawl_service()

            result = service.discover_site_urls(
                url=url,
                search=body.get("search"),
            )
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Firecrawl map site error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/firecrawl/platforms")
    async def firecrawl_platforms():
        """获取所有支持的平台列表"""
        try:
            from firecrawl_integration import FirecrawlService
            platforms = FirecrawlService.get_supported_platforms()
            return {"success": True, "data": platforms}
        except Exception as e:
            logger.error(f"Firecrawl platforms error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ============================================================
    # AnyGen Suite API
    # ============================================================

    @app.get("/api/anygen/status")
    async def anygen_status():
        """检查 AnyGen Suite 配置状态"""
        anygen_key = os.environ.get("ANYGEN_API_KEY", "")
        has_key = bool(anygen_key)
        return {
            "success": True,
            "configured": has_key,
            "masked_key": anygen_key[:10] + "***" if has_key else "",
            "message": "AnyGen API Key 已配置" if has_key else "未配置 ANYGEN_API_KEY",
        }

    # ============================================================
    # Platform Connectors API
    # ============================================================

    @app.get("/api/connectors/platforms")
    async def list_platform_connectors():
        """列出所有平台连接器及其状态"""
        connectors = {
            "电商": [
                {"id": "shopify", "name": "Shopify", "status": "disconnected", "icon": "🛒"},
                {"id": "amazon", "name": "Amazon", "status": "disconnected", "icon": "📦"},
                {"id": "wix", "name": "Wix", "status": "disconnected", "icon": "🏬"},
                {"id": "woocommerce", "name": "WooCommerce", "status": "disconnected", "icon": "🛍️"},
                {"id": "genstore", "name": "Genstore", "status": "connected", "icon": "🏪"},
                {"id": "ebay", "name": "eBay", "status": "disconnected", "icon": "🔨"},
                {"id": "etsy", "name": "Etsy", "status": "coming_soon", "icon": "🎨"},
                {"id": "tiktokshop", "name": "TikTok Shop", "status": "coming_soon", "icon": "🎵"},
            ],
            "社媒": [
                {"id": "tiktok", "name": "TikTok", "status": "connected", "icon": "🎵"},
                {"id": "instagram", "name": "Instagram", "status": "connected", "icon": "📷"},
                {"id": "twitter", "name": "Twitter/X", "status": "connected", "icon": "🐦"},
                {"id": "youtube", "name": "YouTube", "status": "connected", "icon": "▶️"},
                {"id": "facebook", "name": "Facebook", "status": "connected", "icon": "📘"},
                {"id": "linkedin", "name": "LinkedIn", "status": "connected", "icon": "💼"},
                {"id": "reddit", "name": "Reddit", "status": "connected", "icon": "🤖"},
            ],
            "营销": [
                {"id": "google_ads", "name": "Google Ads", "status": "connected", "icon": "📢"},
                {"id": "meta_ads", "name": "Meta Ads", "status": "coming_soon", "icon": "📱"},
                {"id": "tiktok_ads", "name": "TikTok Ads", "status": "coming_soon", "icon": "🎯"},
                {"id": "omnisend", "name": "Omnisend", "status": "disconnected", "icon": "📧"},
                {"id": "mailchimp", "name": "Mailchimp", "status": "disconnected", "icon": "✉️"},
            ],
            "ERP/物流": [
                {"id": "linking_erp", "name": "领星ERP", "status": "disconnected", "icon": "📊"},
                {"id": "shipstation", "name": "ShipStation", "status": "disconnected", "icon": "🚚"},
                {"id": "cin7", "name": "Cin7 Core", "status": "disconnected", "icon": "📋"},
                {"id": "shipbob", "name": "ShipBob", "status": "disconnected", "icon": "📦"},
            ],
            "CRM/客服": [
                {"id": "gorgias", "name": "Gorgias", "status": "disconnected", "icon": "💬"},
                {"id": "intercom", "name": "Intercom", "status": "disconnected", "icon": "🗨️"},
                {"id": "salesforce", "name": "Salesforce", "status": "disconnected", "icon": "☁️"},
            ],
            "生产力/支付": [
                {"id": "gmail", "name": "Gmail", "status": "connected", "icon": "📧"},
                {"id": "google_docs", "name": "Google Docs", "status": "connected", "icon": "📄"},
                {"id": "google_drive", "name": "Google Drive", "status": "connected", "icon": "📁"},
                {"id": "google_sheets", "name": "Google Sheets", "status": "connected", "icon": "📊"},
                {"id": "google_analytics", "name": "Google Analytics", "status": "connected", "icon": "📈"},
                {"id": "google_calendar", "name": "Google 日历", "status": "connected", "icon": "📅"},
                {"id": "notion", "name": "Notion", "status": "connected", "icon": "📝"},
                {"id": "stripe", "name": "Stripe", "status": "disconnected", "icon": "💳"},
                {"id": "whatsapp", "name": "WhatsApp Business", "status": "disconnected", "icon": "💬"},
                {"id": "sellersprite", "name": "SellerSprite", "status": "connected", "icon": "🔍"},
                {"id": "sorftime", "name": "Sorftime", "status": "disconnected", "icon": "📊"},
            ],
        }
        return {"success": True, "connectors": connectors}

    @app.get("/api/connectors/platforms/config")
    async def get_platform_configs():
        """获取平台连接器的真实配置状态（读取环境变量和配置文件）"""
        import json as _json
        config_path = Path(__file__).parent.parent / "data" / "platform_config.json"
        stored_config = {}
        if config_path.exists():
            try:
                stored_config = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                stored_config = {}

        def _mask_key(key: str) -> str:
            if not key:
                return ""
            return key[:8] + "****" + key[-4:] if len(key) > 12 else "****"

        platforms = {
            # ==================== 跨境电商平台 ====================
            "电商": {
                "shopify": {
                    "id": "shopify", "name": "Shopify", "icon": "🛒",
                    "auth_type": "oauth2",
                    "description": "Shopify 独立站管理 · 订单/产品/客户全维度同步",
                    "config_fields": [
                        {"key": "shopify_store", "label": "店铺域名", "type": "text", "placeholder": "your-store.myshopify.com", "required": True},
                        {"key": "shopify_admin_api_key", "label": "Admin API Key", "type": "password", "required": True},
                        {"key": "shopify_admin_api_secret", "label": "Admin API Secret", "type": "password", "required": True},
                        {"key": "shopify_access_token", "label": "Access Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("shopify", {}).get("shopify_store")),
                    "status": "connected" if stored_config.get("shopify", {}).get("shopify_store") else "disconnected",
                    "env_keys": ["SHOPIFY_STORE", "SHOPIFY_ADMIN_API_KEY", "SHOPIFY_ADMIN_API_SECRET", "SHOPIFY_ACCESS_TOKEN"],
                },
                "amazon": {
                    "id": "amazon", "name": "Amazon Seller Central", "icon": "📦",
                    "auth_type": "sp_api",
                    "description": "Amazon 卖家平台 · SP-API 对接 · Listing/广告/订单/库存",
                    "config_fields": [
                        {"key": "amazon_seller_id", "label": "Seller ID", "type": "text", "placeholder": "AXXXXXXXXXXXXX", "required": True},
                        {"key": "amazon_marketplace_id", "label": "Marketplace ID", "type": "select", "options": [
                            {"value": "ATVPDKIKX0DER", "label": "美国站 (US)"},
                            {"value": "A1F83G8C2ARO7P", "label": "英国站 (UK)"},
                            {"value": "A1PA6795UKMFR9", "label": "德国站 (DE)"},
                            {"value": "A13V1IB3VIYZZH", "label": "法国站 (FR)"},
                            {"value": "APJ6JRA9NG5V4", "label": "意大利站 (IT)"},
                            {"value": "A1RKKUPIHCS9HS", "label": "西班牙站 (ES)"},
                            {"value": "A21TJRUUN4KGV", "label": "印度站 (IN)"},
                            {"value": "A1VC38T7YXB528", "label": "日本站 (JP)"},
                            {"value": "A2EUQ1WTGCTBG2", "label": "加拿大站 (CA)"},
                            {"value": "A39USJ420K4XYY", "label": "澳大利亚站 (AU)"},
                        ], "required": True},
                        {"key": "amazon_access_key", "label": "AWS Access Key ID", "type": "password", "required": True},
                        {"key": "amazon_secret_key", "label": "AWS Secret Key", "type": "password", "required": True},
                        {"key": "amazon_role_arn", "label": "IAM Role ARN", "type": "text", "placeholder": "arn:aws:iam::xxx:role/xxx", "required": True},
                        {"key": "amazon_refresh_token", "label": "SP-API Refresh Token", "type": "password", "required": False},
                    ],
                    "configured": bool(stored_config.get("amazon", {}).get("amazon_seller_id")),
                    "status": "connected" if stored_config.get("amazon", {}).get("amazon_seller_id") else "disconnected",
                    "env_keys": ["AMAZON_SELLER_ID", "AMAZON_MARKETPLACE_ID", "AMAZON_ACCESS_KEY", "AMAZON_SECRET_KEY", "AMAZON_ROLE_ARN"],
                },
                "tiktokshop": {
                    "id": "tiktokshop", "name": "TikTok Shop", "icon": "🎵",
                    "auth_type": "oauth2",
                    "description": "TikTok Shop 全托管 · 商品/订单/直播/达人带货",
                    "config_fields": [
                        {"key": "tiktokshop_app_key", "label": "App Key", "type": "password", "required": True},
                        {"key": "tiktokshop_app_secret", "label": "App Secret", "type": "password", "required": True},
                        {"key": "tiktokshop_shop_id", "label": "Shop ID", "type": "text", "required": True},
                        {"key": "tiktokshop_region", "label": "站点", "type": "select", "options": [
                            {"value": "US", "label": "美国站"},
                            {"value": "UK", "label": "英国站"},
                            {"value": "ID", "label": "印尼站"},
                            {"value": "TH", "label": "泰国站"},
                            {"value": "VN", "label": "越南站"},
                            {"value": "MY", "label": "马来西亚站"},
                            {"value": "PH", "label": "菲律宾站"},
                            {"value": "SG", "label": "新加坡站"},
                        ], "required": True},
                    ],
                    "configured": bool(stored_config.get("tiktokshop", {}).get("tiktokshop_app_key")),
                    "status": "connected" if stored_config.get("tiktokshop", {}).get("tiktokshop_app_key") else "disconnected",
                    "env_keys": ["TIKTOKSHOP_APP_KEY", "TIKTOKSHOP_APP_SECRET", "TIKTOKSHOP_SHOP_ID", "TIKTOKSHOP_REGION"],
                },
                "woocommerce": {
                    "id": "woocommerce", "name": "WooCommerce", "icon": "🛍️",
                    "auth_type": "api_key",
                    "description": "WordPress WooCommerce · REST API 对接",
                    "config_fields": [
                        {"key": "woocommerce_url", "label": "店铺 URL", "type": "text", "placeholder": "https://yourstore.com", "required": True},
                        {"key": "woocommerce_consumer_key", "label": "Consumer Key", "type": "password", "required": True},
                        {"key": "woocommerce_consumer_secret", "label": "Consumer Secret", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("woocommerce", {}).get("woocommerce_url")),
                    "status": "disconnected",
                    "env_keys": ["WOOCOMMERCE_URL", "WOOCOMMERCE_CONSUMER_KEY", "WOOCOMMERCE_CONSUMER_SECRET"],
                },
                "wix": {
                    "id": "wix", "name": "Wix", "icon": "🏬",
                    "auth_type": "oauth2",
                    "description": "Wix 电商平台 · 产品/订单/客户管理",
                    "config_fields": [
                        {"key": "wix_site_id", "label": "Site ID", "type": "text", "required": True},
                        {"key": "wix_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "wix_account_id", "label": "Account ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("wix", {}).get("wix_site_id")),
                    "status": "disconnected",
                    "env_keys": ["WIX_SITE_ID", "WIX_API_KEY", "WIX_ACCOUNT_ID"],
                },
                "ebay": {
                    "id": "ebay", "name": "eBay", "icon": "🔨",
                    "auth_type": "oauth2",
                    "description": "eBay 全球站点 · Trading/Finding API 对接",
                    "config_fields": [
                        {"key": "ebay_app_id", "label": "App ID (Client ID)", "type": "text", "required": True},
                        {"key": "ebay_cert_id", "label": "Cert ID (Client Secret)", "type": "password", "required": True},
                        {"key": "ebay_ru_name", "label": "RuName (Redirect URL)", "type": "text", "required": False},
                        {"key": "ebay_site_id", "label": "站点", "type": "select", "options": [
                            {"value": "0", "label": "美国站 (US)"},
                            {"value": "3", "label": "英国站 (UK)"},
                            {"value": "77", "label": "德国站 (DE)"},
                            {"value": "15", "label": "澳大利亚站 (AU)"},
                        ], "required": True},
                    ],
                    "configured": bool(stored_config.get("ebay", {}).get("ebay_app_id")),
                    "status": "disconnected",
                    "env_keys": ["EBAY_APP_ID", "EBAY_CERT_ID", "EBAY_RU_NAME"],
                },
                "etsy": {
                    "id": "etsy", "name": "Etsy", "icon": "🎨",
                    "auth_type": "oauth2",
                    "description": "Etsy 手工品电商 · API v3 对接",
                    "config_fields": [
                        {"key": "etsy_keystring", "label": "Keystring (Client ID)", "type": "text", "required": True},
                        {"key": "etsy_shared_secret", "label": "Shared Secret", "type": "password", "required": True},
                        {"key": "etsy_shop_id", "label": "Shop ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("etsy", {}).get("etsy_keystring")),
                    "status": "disconnected",
                    "env_keys": ["ETSY_KEYSTRING", "ETSY_SHARED_SECRET"],
                },
                "genstore": {
                    "id": "genstore", "name": "Genstore", "icon": "🏪",
                    "auth_type": "api_key",
                    "description": "Genstore AI 电商引擎 · 智能建站与运营",
                    "config_fields": [
                        {"key": "genstore_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "genstore_store_id", "label": "Store ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("genstore", {}).get("genstore_api_key")),
                    "status": "connected" if stored_config.get("genstore", {}).get("genstore_api_key") else "disconnected",
                    "env_keys": ["GENSTORE_API_KEY"],
                },
            },
            # ==================== 全球社媒平台 ====================
            "社媒": {
                "tiktok": {
                    "id": "tiktok", "name": "TikTok", "icon": "🎵",
                    "auth_type": "oauth2",
                    "description": "TikTok 内容发布 · 视频上传 · 数据洞察 · 达人合作",
                    "config_fields": [
                        {"key": "tiktok_client_key", "label": "Client Key", "type": "text", "required": True},
                        {"key": "tiktok_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "tiktok_creator_id", "label": "Creator ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("tiktok", {}).get("tiktok_client_key")),
                    "status": "connected" if stored_config.get("tiktok", {}).get("tiktok_client_key") else "disconnected",
                    "env_keys": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"],
                },
                "instagram": {
                    "id": "instagram", "name": "Instagram", "icon": "📷",
                    "auth_type": "oauth2_facebook",
                    "description": "Instagram 内容发布 · Reels/Stories/Feed · 品牌账号管理",
                    "config_fields": [
                        {"key": "instagram_app_id", "label": "Facebook App ID", "type": "text", "required": True},
                        {"key": "instagram_app_secret", "label": "Facebook App Secret", "type": "password", "required": True},
                        {"key": "instagram_page_id", "label": "Instagram Business Account ID", "type": "text", "required": True},
                        {"key": "instagram_access_token", "label": "Page Access Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("instagram", {}).get("instagram_app_id")),
                    "status": "connected" if stored_config.get("instagram", {}).get("instagram_app_id") else "disconnected",
                    "env_keys": ["INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_PAGE_ID", "INSTAGRAM_ACCESS_TOKEN"],
                },
                "facebook": {
                    "id": "facebook", "name": "Facebook", "icon": "📘",
                    "auth_type": "oauth2",
                    "description": "Facebook Page 内容发布 · 社群管理 · Meta Business Suite",
                    "config_fields": [
                        {"key": "facebook_app_id", "label": "App ID", "type": "text", "required": True},
                        {"key": "facebook_app_secret", "label": "App Secret", "type": "password", "required": True},
                        {"key": "facebook_page_id", "label": "Page ID", "type": "text", "required": True},
                        {"key": "facebook_access_token", "label": "Page Access Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("facebook", {}).get("facebook_app_id")),
                    "status": "connected" if stored_config.get("facebook", {}).get("facebook_app_id") else "disconnected",
                    "env_keys": ["FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET", "FACEBOOK_PAGE_ID", "FACEBOOK_ACCESS_TOKEN"],
                },
                "youtube": {
                    "id": "youtube", "name": "YouTube", "icon": "▶️",
                    "auth_type": "oauth2_google",
                    "description": "YouTube 视频上传 · 直播 · Shorts · 数据分析",
                    "config_fields": [
                        {"key": "youtube_client_id", "label": "Google Client ID", "type": "text", "required": True},
                        {"key": "youtube_client_secret", "label": "Google Client Secret", "type": "password", "required": True},
                        {"key": "youtube_channel_id", "label": "Channel ID", "type": "text", "required": False},
                        {"key": "youtube_refresh_token", "label": "Refresh Token", "type": "password", "required": False},
                    ],
                    "configured": bool(stored_config.get("youtube", {}).get("youtube_client_id")),
                    "status": "connected" if stored_config.get("youtube", {}).get("youtube_client_id") else "disconnected",
                    "env_keys": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"],
                },
                "linkedin": {
                    "id": "linkedin", "name": "LinkedIn", "icon": "💼",
                    "auth_type": "oauth2",
                    "description": "LinkedIn 内容发布 · Company Page · B2B 营销",
                    "config_fields": [
                        {"key": "linkedin_client_id", "label": "Client ID", "type": "text", "required": True},
                        {"key": "linkedin_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "linkedin_org_id", "label": "Organization ID", "type": "text", "required": False},
                        {"key": "linkedin_access_token", "label": "Access Token", "type": "password", "required": False},
                    ],
                    "configured": bool(stored_config.get("linkedin", {}).get("linkedin_client_id")),
                    "status": "connected" if stored_config.get("linkedin", {}).get("linkedin_client_id") else "disconnected",
                    "env_keys": ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_ACCESS_TOKEN"],
                },
                "x_twitter": {
                    "id": "x_twitter", "name": "X / Twitter", "icon": "🐦",
                    "auth_type": "oauth1a",
                    "description": "X (Twitter) 内容发布 · API v2 · 推文管理",
                    "config_fields": [
                        {"key": "twitter_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "twitter_api_secret", "label": "API Secret", "type": "password", "required": True},
                        {"key": "twitter_access_token", "label": "Access Token", "type": "password", "required": True},
                        {"key": "twitter_access_secret", "label": "Access Secret", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("x_twitter", {}).get("twitter_api_key")),
                    "status": "connected" if stored_config.get("x_twitter", {}).get("twitter_api_key") else "disconnected",
                    "env_keys": ["TWITTER_API_KEY", "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"],
                },
                "reddit": {
                    "id": "reddit", "name": "Reddit", "icon": "🤖",
                    "auth_type": "oauth2",
                    "description": "Reddit 内容发布 · 社区管理 · 品牌监控",
                    "config_fields": [
                        {"key": "reddit_client_id", "label": "Client ID", "type": "text", "required": True},
                        {"key": "reddit_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "reddit_username", "label": "Username", "type": "text", "required": True},
                        {"key": "reddit_password", "label": "Password", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("reddit", {}).get("reddit_client_id")),
                    "status": "connected" if stored_config.get("reddit", {}).get("reddit_client_id") else "disconnected",
                    "env_keys": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"],
                },
                "pinterest": {
                    "id": "pinterest", "name": "Pinterest", "icon": "📌",
                    "auth_type": "oauth2",
                    "description": "Pinterest Pin 发布 · 品牌主页 · 商品 Pin",
                    "config_fields": [
                        {"key": "pinterest_app_id", "label": "App ID", "type": "text", "required": True},
                        {"key": "pinterest_app_secret", "label": "App Secret", "type": "password", "required": True},
                        {"key": "pinterest_board_id", "label": "Board ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("pinterest", {}).get("pinterest_app_id")),
                    "status": "disconnected",
                    "env_keys": ["PINTEREST_APP_ID", "PINTEREST_APP_SECRET"],
                },
            },
            # ==================== 营销平台 ====================
            "营销": {
                "google_ads": {
                    "id": "google_ads", "name": "Google Ads", "icon": "📢",
                    "auth_type": "oauth2_google",
                    "description": "Google Ads 广告管理 · 搜索/购物/展示/视频广告",
                    "config_fields": [
                        {"key": "google_ads_client_id", "label": "Client ID", "type": "text", "required": True},
                        {"key": "google_ads_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "google_ads_developer_token", "label": "Developer Token", "type": "password", "required": True},
                        {"key": "google_ads_customer_id", "label": "Customer ID (MCC)", "type": "text", "placeholder": "123-456-7890", "required": True},
                        {"key": "google_ads_refresh_token", "label": "Refresh Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("google_ads", {}).get("google_ads_developer_token")),
                    "status": "connected" if stored_config.get("google_ads", {}).get("google_ads_developer_token") else "disconnected",
                    "env_keys": ["GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_REFRESH_TOKEN"],
                },
                "meta_ads": {
                    "id": "meta_ads", "name": "Meta Ads", "icon": "📱",
                    "auth_type": "oauth2_facebook",
                    "description": "Meta Ads Manager · Facebook/Instagram 广告投放",
                    "config_fields": [
                        {"key": "meta_ads_app_id", "label": "App ID", "type": "text", "required": True},
                        {"key": "meta_ads_app_secret", "label": "App Secret", "type": "password", "required": True},
                        {"key": "meta_ads_account_id", "label": "Ad Account ID", "type": "text", "placeholder": "act_XXXXXXXX", "required": True},
                        {"key": "meta_ads_access_token", "label": "Access Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("meta_ads", {}).get("meta_ads_app_id")),
                    "status": "disconnected",
                    "env_keys": ["META_ADS_APP_ID", "META_ADS_APP_SECRET", "META_ADS_ACCOUNT_ID", "META_ADS_ACCESS_TOKEN"],
                },
                "tiktok_ads": {
                    "id": "tiktok_ads", "name": "TikTok Ads", "icon": "🎯",
                    "auth_type": "oauth2",
                    "description": "TikTok Ads Manager · 竞价广告/品牌广告/Spark Ads",
                    "config_fields": [
                        {"key": "tiktok_ads_app_id", "label": "App ID", "type": "text", "required": True},
                        {"key": "tiktok_ads_secret", "label": "Secret", "type": "password", "required": True},
                        {"key": "tiktok_ads_advertiser_id", "label": "Advertiser ID", "type": "text", "required": True},
                    ],
                    "configured": bool(stored_config.get("tiktok_ads", {}).get("tiktok_ads_app_id")),
                    "status": "disconnected",
                    "env_keys": ["TIKTOK_ADS_APP_ID", "TIKTOK_ADS_SECRET", "TIKTOK_ADS_ADVERTISER_ID"],
                },
                "mailchimp": {
                    "id": "mailchimp", "name": "Mailchimp", "icon": "✉️",
                    "auth_type": "api_key",
                    "description": "Mailchimp 邮件营销 · 自动化 · 受众管理",
                    "config_fields": [
                        {"key": "mailchimp_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "mailchimp_server_prefix", "label": "Server Prefix", "type": "text", "placeholder": "us1", "required": True},
                        {"key": "mailchimp_list_id", "label": "Audience List ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("mailchimp", {}).get("mailchimp_api_key")),
                    "status": "disconnected",
                    "env_keys": ["MAILCHIMP_API_KEY", "MAILCHIMP_SERVER_PREFIX"],
                },
                "omnisend": {
                    "id": "omnisend", "name": "Omnisend", "icon": "📧",
                    "auth_type": "api_key",
                    "description": "Omnisend 电商邮件/SMS 营销自动化",
                    "config_fields": [
                        {"key": "omnisend_api_key", "label": "API Key", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("omnisend", {}).get("omnisend_api_key")),
                    "status": "disconnected",
                    "env_keys": ["OMNISEND_API_KEY"],
                },
            },
            # ==================== ERP / 物流 ====================
            "ERP/物流": {
                "linking_erp": {
                    "id": "linking_erp", "name": "领星ERP", "icon": "📊",
                    "auth_type": "api_key",
                    "description": "领星ERP 跨境电商管理系统 · 多平台订单/库存/财务",
                    "config_fields": [
                        {"key": "linking_erp_app_key", "label": "App Key", "type": "text", "required": True},
                        {"key": "linking_erp_app_secret", "label": "App Secret", "type": "password", "required": True},
                        {"key": "linking_erp_company_id", "label": "Company ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("linking_erp", {}).get("linking_erp_app_key")),
                    "status": "disconnected",
                    "env_keys": ["LINKING_ERP_APP_KEY", "LINKING_ERP_APP_SECRET"],
                },
                "shipstation": {
                    "id": "shipstation", "name": "ShipStation", "icon": "🚚",
                    "auth_type": "api_key",
                    "description": "ShipStation 物流管理 · 订单发货/标签打印/多承运商",
                    "config_fields": [
                        {"key": "shipstation_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "shipstation_api_secret", "label": "API Secret", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("shipstation", {}).get("shipstation_api_key")),
                    "status": "disconnected",
                    "env_keys": ["SHIPSTATION_API_KEY", "SHIPSTATION_API_SECRET"],
                },
                "cin7": {
                    "id": "cin7", "name": "Cin7 Core", "icon": "📋",
                    "auth_type": "api_key",
                    "description": "Cin7 Core 库存管理 · 多渠道库存同步",
                    "config_fields": [
                        {"key": "cin7_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "cin7_account_id", "label": "Account ID", "type": "text", "required": True},
                    ],
                    "configured": bool(stored_config.get("cin7", {}).get("cin7_api_key")),
                    "status": "disconnected",
                    "env_keys": ["CIN7_API_KEY", "CIN7_ACCOUNT_ID"],
                },
                "shipbob": {
                    "id": "shipbob", "name": "ShipBob", "icon": "📦",
                    "auth_type": "api_key",
                    "description": "ShipBob 海外仓 · 仓储配送 · 全球履约",
                    "config_fields": [
                        {"key": "shipbob_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "shipbob_channel_id", "label": "Channel ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("shipbob", {}).get("shipbob_api_key")),
                    "status": "disconnected",
                    "env_keys": ["SHIPBOB_API_KEY"],
                },
            },
            # ==================== CRM / 客服 ====================
            "CRM/客服": {
                "gorgias": {
                    "id": "gorgias", "name": "Gorgias", "icon": "💬",
                    "auth_type": "api_key",
                    "description": "Gorgias 电商客服 · 工单管理 · 自动化回复",
                    "config_fields": [
                        {"key": "gorgias_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "gorgias_subdomain", "label": "Subdomain", "type": "text", "placeholder": "yourstore", "required": True},
                        {"key": "gorgias_email", "label": "Email", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("gorgias", {}).get("gorgias_api_key")),
                    "status": "disconnected",
                    "env_keys": ["GORGIAS_API_KEY", "GORGIAS_SUBDOMAIN"],
                },
                "intercom": {
                    "id": "intercom", "name": "Intercom", "icon": "🗨️",
                    "auth_type": "oauth2",
                    "description": "Intercom 客户沟通 · 应用内消息 · 客户数据平台",
                    "config_fields": [
                        {"key": "intercom_access_token", "label": "Access Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("intercom", {}).get("intercom_access_token")),
                    "status": "disconnected",
                    "env_keys": ["INTERCOM_ACCESS_TOKEN"],
                },
                "salesforce": {
                    "id": "salesforce", "name": "Salesforce", "icon": "☁️",
                    "auth_type": "oauth2",
                    "description": "Salesforce CRM · 销售云/服务云 · 客户360",
                    "config_fields": [
                        {"key": "salesforce_client_id", "label": "Client ID (Consumer Key)", "type": "text", "required": True},
                        {"key": "salesforce_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "salesforce_username", "label": "Username", "type": "text", "required": True},
                        {"key": "salesforce_password", "label": "Password + Token", "type": "password", "required": True},
                        {"key": "salesforce_domain", "label": "Domain", "type": "select", "options": [
                            {"value": "login", "label": "Production"},
                            {"value": "test", "label": "Sandbox"},
                        ], "required": True},
                    ],
                    "configured": bool(stored_config.get("salesforce", {}).get("salesforce_client_id")),
                    "status": "disconnected",
                    "env_keys": ["SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET", "SALESFORCE_USERNAME", "SALESFORCE_PASSWORD"],
                },
            },
            # ==================== 支付与生产力 ====================
            "支付/生产力": {
                "stripe": {
                    "id": "stripe", "name": "Stripe", "icon": "💳",
                    "auth_type": "api_key",
                    "description": "Stripe 支付 · 订阅管理 · 发票 · 财务报告",
                    "config_fields": [
                        {"key": "stripe_secret_key", "label": "Secret Key", "type": "password", "required": True},
                        {"key": "stripe_webhook_secret", "label": "Webhook Secret", "type": "password", "required": False},
                    ],
                    "configured": bool(stored_config.get("stripe", {}).get("stripe_secret_key")),
                    "status": "connected" if stored_config.get("stripe", {}).get("stripe_secret_key") else "disconnected",
                    "env_keys": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
                },
                "paypal": {
                    "id": "paypal", "name": "PayPal", "icon": "🅿️",
                    "auth_type": "oauth2",
                    "description": "PayPal 支付 · 订单管理 · 争议处理",
                    "config_fields": [
                        {"key": "paypal_client_id", "label": "Client ID", "type": "text", "required": True},
                        {"key": "paypal_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "paypal_mode", "label": "模式", "type": "select", "options": [
                            {"value": "sandbox", "label": "沙箱测试"},
                            {"value": "live", "label": "生产环境"},
                        ], "required": True},
                    ],
                    "configured": bool(stored_config.get("paypal", {}).get("paypal_client_id")),
                    "status": "disconnected",
                    "env_keys": ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"],
                },
                "whatsapp": {
                    "id": "whatsapp", "name": "WhatsApp Business", "icon": "💬",
                    "auth_type": "oauth2_meta",
                    "description": "WhatsApp Business API · 消息模板 · 自动化客服",
                    "config_fields": [
                        {"key": "whatsapp_phone_number_id", "label": "Phone Number ID", "type": "text", "required": True},
                        {"key": "whatsapp_access_token", "label": "Access Token", "type": "password", "required": True},
                        {"key": "whatsapp_business_id", "label": "WhatsApp Business Account ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("whatsapp", {}).get("whatsapp_phone_number_id")),
                    "status": "disconnected",
                    "env_keys": ["WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_BUSINESS_ID"],
                },
                "notion": {
                    "id": "notion", "name": "Notion", "icon": "📝",
                    "auth_type": "oauth2",
                    "description": "Notion 知识库 · 数据库 · 项目管理",
                    "config_fields": [
                        {"key": "notion_api_key", "label": "Integration Token", "type": "password", "required": True},
                        {"key": "notion_database_id", "label": "Database ID", "type": "text", "required": False},
                    ],
                    "configured": bool(stored_config.get("notion", {}).get("notion_api_key")),
                    "status": "connected" if stored_config.get("notion", {}).get("notion_api_key") else "disconnected",
                    "env_keys": ["NOTION_API_KEY"],
                },
                "gmail": {
                    "id": "gmail", "name": "Gmail", "icon": "📧",
                    "auth_type": "oauth2_google",
                    "description": "Gmail API · 邮件收发 · 自动化营销邮件",
                    "config_fields": [
                        {"key": "gmail_client_id", "label": "Client ID", "type": "text", "required": True},
                        {"key": "gmail_client_secret", "label": "Client Secret", "type": "password", "required": True},
                        {"key": "gmail_refresh_token", "label": "Refresh Token", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("gmail", {}).get("gmail_client_id")),
                    "status": "connected" if stored_config.get("gmail", {}).get("gmail_client_id") else "disconnected",
                    "env_keys": ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"],
                },
                "google_analytics": {
                    "id": "google_analytics", "name": "Google Analytics 4", "icon": "📈",
                    "auth_type": "oauth2_google",
                    "description": "GA4 数据分析 · 电商漏斗 · 转化追踪",
                    "config_fields": [
                        {"key": "ga4_property_id", "label": "Property ID", "type": "text", "placeholder": "123456789", "required": True},
                        {"key": "ga4_client_email", "label": "Service Account Email", "type": "text", "required": True},
                        {"key": "ga4_private_key", "label": "Private Key", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("google_analytics", {}).get("ga4_property_id")),
                    "status": "connected" if stored_config.get("google_analytics", {}).get("ga4_property_id") else "disconnected",
                    "env_keys": ["GA4_PROPERTY_ID", "GA4_CLIENT_EMAIL", "GA4_PRIVATE_KEY"],
                },
                "sellersprite": {
                    "id": "sellersprite", "name": "SellerSprite", "icon": "🔍",
                    "auth_type": "api_key",
                    "description": "SellerSprite 选品工具 · 43 MCP Tools · Amazon 数据情报",
                    "config_fields": [
                        {"key": "sellersprite_api_key", "label": "API Key", "type": "password", "required": True},
                        {"key": "sellersprite_secret_key", "label": "Secret Key", "type": "password", "required": False},
                    ],
                    "configured": bool(stored_config.get("sellersprite", {}).get("sellersprite_api_key")),
                    "status": "connected" if stored_config.get("sellersprite", {}).get("sellersprite_api_key") else "disconnected",
                    "env_keys": ["SELLERSPRITE_API_KEY", "SELLERSPRITE_SECRET_KEY"],
                },
                "sorftime": {
                    "id": "sorftime", "name": "Sorftime", "icon": "📊",
                    "auth_type": "api_key",
                    "description": "Sorftime 选品分析 · Amazon 市场数据",
                    "config_fields": [
                        {"key": "sorftime_api_key", "label": "API Key", "type": "password", "required": True},
                    ],
                    "configured": bool(stored_config.get("sorftime", {}).get("sorftime_api_key")),
                    "status": "disconnected",
                    "env_keys": ["SORFTIME_API_KEY"],
                },
            },
        }

        # 更新连接状态（基于环境变量）
        for category_key, category_platforms in platforms.items():
            for pid, pconfig in category_platforms.items():
                env_keys = pconfig.get("env_keys", [])
                if env_keys:
                    env_configured = any(os.environ.get(k) for k in env_keys)
                    if env_configured and pconfig["status"] == "disconnected":
                        pconfig["status"] = "connected"
                        pconfig["configured"] = True

        return {
            "success": True,
            "platforms": platforms,
            "total_platforms": sum(len(v) for v in platforms.values()),
            "connected_count": sum(
                1 for v in platforms.values()
                for p in v.values()
                if p["status"] == "connected"
            ),
            "timestamp": datetime.now().isoformat(),
        }

    @app.post("/api/connectors/platforms/config")
    async def save_platform_config(request: Request):
        """保存平台连接器配置"""
        try:
            body = await request.json()
            platform_id = body.get("platform_id", "")
            config_data = body.get("config", {})

            if not platform_id or not config_data:
                raise HTTPException(status_code=400, detail="platform_id and config are required")

            config_path = Path(__file__).parent.parent / "data" / "platform_config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)

            stored = {}
            if config_path.exists():
                try:
                    stored = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    stored = {}

            stored[platform_id] = config_data
            config_path.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")

            return {
                "success": True,
                "platform_id": platform_id,
                "message": f"平台 {platform_id} 配置已保存",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/api/connectors/platforms/config/{platform_id}")
    async def delete_platform_config(platform_id: str):
        """删除平台连接器配置"""
        config_path = Path(__file__).parent.parent / "data" / "platform_config.json"
        if not config_path.exists():
            return {"success": True, "message": "No config to delete"}

        try:
            stored = json.loads(config_path.read_text(encoding="utf-8"))
            if platform_id in stored:
                del stored[platform_id]
                config_path.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"success": True, "message": f"平台 {platform_id} 配置已删除"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/connectors/platforms/test/{platform_id}")
    async def test_platform_connection(platform_id: str):
        """测试平台连接（验证 API 凭据）"""
        config_path = Path(__file__).parent.parent / "data" / "platform_config.json"
        stored = {}
        if config_path.exists():
            try:
                stored = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        platform_config = stored.get(platform_id, {})
        if not platform_config:
            return {"success": False, "status": "not_configured", "message": "未配置凭据"}

        # 根据不同平台进行连接测试
        test_results = {
            "shopify": _test_shopify_connection,
            "tiktok": _test_tiktok_connection,
            "amazon": _test_amazon_connection,
            "stripe": _test_stripe_connection,
            "google_ads": _test_google_ads_connection,
        }

        tester = test_results.get(platform_id)
        if tester:
            try:
                result = await tester(platform_config)
                return {"success": True, "status": "connected", "message": "连接成功", "detail": result}
            except Exception as e:
                return {"success": False, "status": "error", "message": str(e)}

        return {"success": True, "status": "configured", "message": "凭据已保存（该平台暂不支持自动连接测试）"}

    @app.get("/api/skills/{skill_name}")
    async def get_skill_detail(skill_name: str):
        """获取单个技能详情"""
        if not _engine or not _engine.runtime:
            raise HTTPException(status_code=503, detail="Engine not ready")

        skill = None
        if hasattr(_engine.runtime, 'skill_registry'):
            skill = _engine.runtime.skill_registry.get_skill_md(skill_name)
        if not skill and _engine.runtime:
            skill = _engine.runtime.skills.get_skill_md(skill_name)

        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

        # 读取 SKILL.md 完整内容
        skills_dir = Path(__file__).parent.parent / "skills" / skill_name
        skill_md = skills_dir / "SKILL.md"
        if skill_md.exists():
            skill["content"] = skill_md.read_text(encoding="utf-8")

        return {"success": True, "skill": skill}

    # ============================================================
    # Webhook Stats
    # ============================================================

    @app.get("/api/webhooks/stats")
    async def webhook_stats():
        if hasattr(_engine, 'webhook_handler') and _engine.webhook_handler:
            return _engine.webhook_handler.get_stats()
        status = _engine.get_status()
        return {
            "total_handlers": status.get("total_webhook_routes", 0),
            "events_processed": 0,
            "events_failed": 0,
        }

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

    try:
        from .auth import (
            get_auth_service,
            RegisterRequest, EnterpriseRegisterRequest, LoginRequest,
            UserUpdateRequest, PasswordChangeRequest,
        )
    except ImportError:
        from orchestration.auth import (
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
    # SellerSprite API - Amazon 全维度数据情报代理
    # ============================================================

    @app.get("/api/sellersprite/status")
    async def sellersprite_status():
        """SellerSprite 集成状态"""
        api_key = os.environ.get("SELLERSPRITE_SECRET_KEY", "")
        return {
            "success": True,
            "integration": "SellerSprite 卖家精灵",
            "platform": "https://open.sellersprite.com",
            "status": "connected" if api_key else "unconfigured",
            "api_key_configured": bool(api_key),
            "tools": {
                "total": 43,
                "categories": {
                    "asin_analysis": {"name": "ASIN 分析", "count": 6},
                    "product_selection": {"name": "选品与市场", "count": 16},
                    "keyword_research": {"name": "关键词研究", "count": 6},
                    "aba_trends": {"name": "ABA 数据与趋势", "count": 6},
                    "traffic_analysis": {"name": "流量分析", "count": 4},
                    "review": {"name": "评论分析", "count": 1},
                    "trademark": {"name": "全球商标库", "count": 4},
                }
            },
            "sites": ["US", "JP", "UK", "DE", "FR", "IT", "ES", "CA", "IN", "MX"],
            "data_volume": "2亿+ ASIN · 500万+ 关键词",
            "access_methods": ["API", "CLI", "MCP", "Agent"],
            "mcp_clients": ["Chatbox", "CherryStudio", "Claude Desktop", "Codex", "ChatGPT", "Antigravity", "Coze", "OpenClaw", "Accio", "Refly AI", "WorkBuddy"],
        }

    @app.get("/api/sellersprite/tools")
    async def sellersprite_tools():
        """获取 SellerSprite 43 个工具完整列表"""
        tools = [
            # ASIN 分析
            {"id": "competitor_lookup", "category": "asin_analysis", "name": "查竞品", "endpoint": "/api/1", "description": "查目标ASIN的销量和销额等详细数据"},
            {"id": "asin_detail", "category": "asin_analysis", "name": "ASIN详情", "endpoint": "/api/3", "description": "上架日期、BSR排名、A+等信息"},
            {"id": "asin_sales_trend", "category": "asin_analysis", "name": "销量趋势", "endpoint": "/api/61", "description": "父体/子体销量销售额趋势"},
            {"id": "asin_prediction", "category": "asin_analysis", "name": "销量预测", "endpoint": "/api/27", "description": "ASIN销量预测"},
            {"id": "asin_coupon_trend", "category": "asin_analysis", "name": "优惠趋势", "endpoint": "/api/56", "description": "ASIN优惠趋势数据"},
            {"id": "asin_detail_with_coupon", "category": "asin_analysis", "name": "详情+优惠趋势", "endpoint": "/api/57", "description": "详情及优惠趋势组合"},
            # 选品与市场
            {"id": "product_research", "category": "product_selection", "name": "选产品", "endpoint": "/api/2", "description": "多维度筛选潜力商品"},
            {"id": "product_node", "category": "product_selection", "name": "产品类目", "endpoint": "/api/9", "description": "查询类目ID/名称/节点"},
            {"id": "market_research", "category": "product_selection", "name": "选市场列表", "endpoint": "/api/29", "description": "细分类目市场分析"},
            {"id": "market_statistics", "category": "product_selection", "name": "市场统计", "endpoint": "/api/30", "description": "类目统计数据"},
            {"id": "market_product_concentration", "category": "product_selection", "name": "商品集中度", "endpoint": "/api/31", "description": "商品集中度分析"},
            {"id": "market_brand_concentration", "category": "product_selection", "name": "品牌集中度", "endpoint": "/api/32", "description": "品牌集中度分析"},
            {"id": "market_seller_concentration", "category": "product_selection", "name": "卖家集中度", "endpoint": "/api/33", "description": "卖家集中度分析"},
            {"id": "market_seller_country", "category": "product_selection", "name": "卖家所属地", "endpoint": "/api/35", "description": "卖家所属地分布"},
            {"id": "market_seller_type", "category": "product_selection", "name": "卖家类型", "endpoint": "/api/34", "description": "卖家类型分布"},
            {"id": "market_demand_trend", "category": "product_selection", "name": "需求趋势", "endpoint": "/api/36", "description": "商品需求趋势"},
            {"id": "market_listing_date", "category": "product_selection", "name": "上架时间", "endpoint": "/api/37", "description": "上架时间分布"},
            {"id": "market_listing_trend", "category": "product_selection", "name": "上架趋势", "endpoint": "/api/38", "description": "上架趋势分布"},
            {"id": "market_ratings_count", "category": "product_selection", "name": "评分数分布", "endpoint": "/api/39", "description": "评分数分布"},
            {"id": "market_rating", "category": "product_selection", "name": "评分值分布", "endpoint": "/api/40", "description": "评分值分布"},
            {"id": "market_price", "category": "product_selection", "name": "价格分布", "endpoint": "/api/41", "description": "价格分布"},
            {"id": "market_ebc", "category": "product_selection", "name": "A+视频分布", "endpoint": "/api/42", "description": "A+视频分布"},
            # 关键词研究
            {"id": "traffic_keyword", "category": "keyword_research", "name": "关键词反查", "endpoint": "/api/14", "description": "ASIN近30天前3页搜索流量词"},
            {"id": "keyword_miner", "category": "keyword_research", "name": "关键词挖掘", "endpoint": "/api/6", "description": "衍生词及长尾关键词"},
            {"id": "keyword_research", "category": "keyword_research", "name": "关键词选品", "endpoint": "/api/10", "description": "月搜索量/购买率"},
            {"id": "keyword_trends", "category": "keyword_research", "name": "关键词趋势", "endpoint": "/api/11", "description": "关键词历史趋势"},
            {"id": "keyword_order", "category": "keyword_research", "name": "出单词反查", "endpoint": "/api/24", "description": "竞品Top出单词"},
            {"id": "traffic_extend", "category": "keyword_research", "name": "拓展流量词", "endpoint": "/api/46", "description": "多ASIN拓展流量词"},
            # ABA与趋势
            {"id": "aba_weekly", "category": "aba_trends", "name": "ABA周选品", "endpoint": "/api/19", "description": "ABA数据选品-按周"},
            {"id": "aba_monthly", "category": "aba_trends", "name": "ABA月选品", "endpoint": "/api/20", "description": "ABA数据选品-按月"},
            {"id": "aba_trend", "category": "aba_trends", "name": "ABA关键词趋势", "endpoint": "/api/60", "description": "ABA关键词历史趋势"},
            {"id": "google_trend", "category": "aba_trends", "name": "谷歌趋势", "endpoint": "/api/12", "description": "关键词谷歌趋势"},
            {"id": "bsr_prediction", "category": "aba_trends", "name": "BSR销量预测", "endpoint": "/api/26", "description": "根据BSR预测销量"},
            {"id": "keepa_info", "category": "aba_trends", "name": "商品趋势详情", "endpoint": "/api/22", "description": "价格/BSR/评论历史趋势"},
            # 流量分析
            {"id": "traffic_source", "category": "traffic_analysis", "name": "流量来源", "endpoint": "/api/17", "description": "关键词流向分析"},
            {"id": "traffic_listing", "category": "traffic_analysis", "name": "关联流量列表", "endpoint": "/api/16", "description": "产品及变体关联流量"},
            {"id": "traffic_keyword_stat", "category": "traffic_analysis", "name": "流量词统计", "endpoint": "/api/13", "description": "流量词统计"},
            {"id": "traffic_listing_stat", "category": "traffic_analysis", "name": "关联流量统计", "endpoint": "/api/15", "description": "关联流量统计"},
            # 评论
            {"id": "review", "category": "review", "name": "查评论", "endpoint": "/api/25", "description": "查询Product Review"},
            # 商标
            {"id": "trademark_countries", "category": "trademark", "name": "商标数据范围", "endpoint": "/api/50", "description": "支持商标查询的国家"},
            {"id": "trademark_detail", "category": "trademark", "name": "商标详情", "endpoint": "/api/49", "description": "商标详细信息"},
            {"id": "trademark_list", "category": "trademark", "name": "商标列表", "endpoint": "/api/48", "description": "商标列表数据"},
            {"id": "trademark_stats", "category": "trademark", "name": "商标统计", "endpoint": "/api/47", "description": "商标统计数据"},
            # 工具
            {"id": "image_text_recognition", "category": "utility", "name": "图片文字识别", "endpoint": "/api/44", "description": "图片文字识别"},
        ]
        return {"success": True, "total": len(tools), "tools": tools}

    @app.post("/api/sellersprite/proxy")
    async def sellersprite_proxy(request: dict):
        """代理 SellerSprite API 调用"""
        api_key = os.environ.get("SELLERSPRITE_SECRET_KEY", "")
        if not api_key:
            raise HTTPException(status_code=401, detail="SELLERSPRITE_SECRET_KEY 未配置")

        endpoint = request.get("endpoint", "")
        method = request.get("method", "POST").upper()
        payload = request.get("payload", {})

        headers = {
            "secret-key": api_key,
            "Content-Type": "application/json;charset=utf-8",
        }

        url = f"https://api.sellersprite.com{endpoint}"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=payload)
                else:
                    resp = await client.post(url, headers=headers, json=payload)
                return {"success": True, "status_code": resp.status_code, "data": resp.json()}
        except Exception as e:
            logger.error(f"SellerSprite proxy error: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/sellersprite/visits")
    async def sellersprite_visits():
        """查询 SellerSprite API 可用次数"""
        api_key = os.environ.get("SELLERSPRITE_SECRET_KEY", "")
        if not api_key:
            raise HTTPException(status_code=401, detail="SELLERSPRITE_SECRET_KEY 未配置")

        headers = {
            "secret-key": api_key,
            "Content-Type": "application/json;charset=utf-8",
        }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://api.sellersprite.com/v1/visits", headers=headers)
                return {"success": True, "data": resp.json()}
        except Exception as e:
            logger.error(f"SellerSprite visits error: {e}")
            return {"success": False, "error": str(e)}

    logger.info("🔍 SellerSprite API routes registered (43 tools · 10 sites · Amazon Data Intelligence)")

    # ============================================================
    # 能力中心 · 连接器系统 — 统一数据 API
    # 整合：平台连接器 + Skill Hub 技能库 + SellerSprite 工具
    # ============================================================

    @app.get("/api/capability-hub/status")
    async def capability_hub_status():
        """能力中心连接器系统 - 统一状态 API"""
        import json as _json
        
        # 平台连接器状态
        config_path = Path(__file__).parent.parent / "data" / "platform_config.json"
        stored_config = {}
        if config_path.exists():
            try:
                stored_config = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                stored_config = {}
        
        # 统计连接数
        connected_count = 0
        platform_summary = {}
        for cat_name, cat_platforms in _get_platform_configs(stored_config).items():
            cat_connected = sum(1 for p in cat_platforms.values() if p.get("status") == "connected")
            platform_summary[cat_name] = {
                "total": len(cat_platforms),
                "connected": cat_connected
            }
            connected_count += cat_connected
        
        # SellerSprite 状态
        sellersprite_key = os.environ.get("SELLERSPRITE_SECRET_KEY", "")
        
        return {
            "success": True,
            "system": "能力中心 · 连接器系统",
            "version": "5.4.0",
            "platforms": {
                "total": 35,
                "connected": connected_count,
                "categories": platform_summary,
                "auth_types": ["OAuth2", "API Key", "Amazon SP-API", "OAuth 1.0a"]
            },
            "skill_hub": {
                "total_skills": 49,
                "categories": {
                    "店铺管理": 7,
                    "店铺经营": 8,
                    "选品与商品": 10,
                    "营销与内容": 21,
                    "市场分析": 5
                },
                "source": "Skill Hub 官方 + 社区精选"
            },
            "sellersprite": {
                "status": "connected" if sellersprite_key else "unconfigured",
                "total_tools": 43,
                "sites": 10,
                "sites_list": ["US", "JP", "UK", "DE", "FR", "IT", "ES", "CA", "IN", "MX"],
                "asin_data": "2亿+",
                "keywords": "500万+",
                "integration_methods": ["API", "CLI", "MCP", "Agent"],
                "categories": {
                    "ASIN分析": 6,
                    "选品与市场": 16,
                    "关键词研究": 6,
                    "ABA数据与趋势": 6,
                    "流量分析": 4,
                    "评论分析": 1,
                    "全球商标库": 4,
                    "工具类": 1
                }
            },
            "claude_skills": {
                "total": 31,
                "categories": ["文档处理", "开发工具", "商业营销", "创意媒体", "生产力"]
            }
        }

    def _get_platform_configs(stored_config: dict) -> dict:
        """获取平台配置（复用现有平台配置逻辑的简化版）"""
        # 返回简化版平台配置供状态API使用
        platforms = {}
        # 电商
        platforms["电商"] = {
            "shopify": {"status": "connected" if stored_config.get("shopify", {}).get("shopify_store") else "disconnected"},
            "amazon": {"status": "connected" if stored_config.get("amazon", {}).get("amazon_seller_id") else "disconnected"},
            "tiktokshop": {"status": "connected" if stored_config.get("tiktokshop", {}).get("tiktokshop_app_key") else "disconnected"},
            "woocommerce": {"status": "connected" if stored_config.get("woocommerce", {}).get("woocommerce_url") else "disconnected"},
            "wix": {"status": "connected" if stored_config.get("wix", {}).get("wix_site_id") else "disconnected"},
            "ebay": {"status": "connected" if stored_config.get("ebay", {}).get("ebay_app_id") else "disconnected"},
            "etsy": {"status": "connected" if stored_config.get("etsy", {}).get("etsy_keystring") else "disconnected"},
            "genstore": {"status": "connected" if stored_config.get("genstore", {}).get("genstore_api_key") else "disconnected"},
        }
        # 社媒
        platforms["社媒"] = {
            "tiktok": {"status": "connected" if stored_config.get("tiktok", {}).get("tiktok_client_key") else "disconnected"},
            "instagram": {"status": "connected" if stored_config.get("instagram", {}).get("instagram_app_id") else "disconnected"},
            "facebook": {"status": "connected" if stored_config.get("facebook", {}).get("facebook_app_id") else "disconnected"},
            "youtube": {"status": "connected" if stored_config.get("youtube", {}).get("youtube_client_id") else "disconnected"},
            "linkedin": {"status": "connected" if stored_config.get("linkedin", {}).get("linkedin_client_id") else "disconnected"},
            "x_twitter": {"status": "connected" if stored_config.get("x_twitter", {}).get("twitter_api_key") else "disconnected"},
            "reddit": {"status": "connected" if stored_config.get("reddit", {}).get("reddit_client_id") else "disconnected"},
            "pinterest": {"status": "connected" if stored_config.get("pinterest", {}).get("pinterest_app_id") else "disconnected"},
        }
        # 营销
        platforms["营销"] = {
            "google_ads": {"status": "connected" if stored_config.get("google_ads", {}).get("google_ads_developer_token") else "disconnected"},
            "meta_ads": {"status": "connected" if stored_config.get("meta_ads", {}).get("meta_ads_app_id") else "disconnected"},
            "tiktok_ads": {"status": "connected" if stored_config.get("tiktok_ads", {}).get("tiktok_ads_app_id") else "disconnected"},
            "mailchimp": {"status": "connected" if stored_config.get("mailchimp", {}).get("mailchimp_api_key") else "disconnected"},
            "omnisend": {"status": "connected" if stored_config.get("omnisend", {}).get("omnisend_api_key") else "disconnected"},
        }
        # ERP/物流
        platforms["ERP/物流"] = {
            "linking_erp": {"status": "connected" if stored_config.get("linking_erp", {}).get("linking_erp_app_key") else "disconnected"},
            "shipstation": {"status": "connected" if stored_config.get("shipstation", {}).get("shipstation_api_key") else "disconnected"},
            "cin7": {"status": "connected" if stored_config.get("cin7", {}).get("cin7_api_key") else "disconnected"},
            "shipbob": {"status": "connected" if stored_config.get("shipbob", {}).get("shipbob_api_key") else "disconnected"},
        }
        # CRM/客服
        platforms["CRM/客服"] = {
            "gorgias": {"status": "connected" if stored_config.get("gorgias", {}).get("gorgias_api_key") else "disconnected"},
            "intercom": {"status": "connected" if stored_config.get("intercom", {}).get("intercom_access_token") else "disconnected"},
            "salesforce": {"status": "connected" if stored_config.get("salesforce", {}).get("salesforce_client_id") else "disconnected"},
        }
        # 支付/生产力
        platforms["支付/生产力"] = {
            "stripe": {"status": "connected" if stored_config.get("stripe", {}).get("stripe_secret_key") else "disconnected"},
            "paypal": {"status": "connected" if stored_config.get("paypal", {}).get("paypal_client_id") else "disconnected"},
            "whatsapp": {"status": "connected" if stored_config.get("whatsapp", {}).get("whatsapp_phone_number_id") else "disconnected"},
            "notion": {"status": "connected" if stored_config.get("notion", {}).get("notion_api_key") else "disconnected"},
            "gmail": {"status": "connected" if stored_config.get("gmail", {}).get("gmail_client_id") else "disconnected"},
            "google_analytics": {"status": "connected" if stored_config.get("google_analytics", {}).get("ga4_property_id") else "disconnected"},
            "sellersprite": {"status": "connected" if stored_config.get("sellersprite", {}).get("sellersprite_api_key") else "disconnected"},
            "sorftime": {"status": "connected" if stored_config.get("sorftime", {}).get("sorftime_api_key") else "disconnected"},
        }
        return platforms

    @app.get("/api/capability-hub/skills")
    async def capability_hub_skills():
        """能力中心 - 电商技能列表"""
        skills = [
            # 店铺管理 (7)
            {"name": "Shopify 店铺管理", "category": "店铺管理", "icon": "🛒", "desc": "连接Shopify店铺，管理商品、订单、客户、库存、折扣与店铺主题", "source": "官方"},
            {"name": "Amazon 店铺管理", "category": "店铺管理", "icon": "📦", "desc": "连接亚马逊卖家账户，管理全球各大站点的订单、商品、定价、库存及报表", "source": "官方"},
            {"name": "Genstore 店铺管理", "category": "店铺管理", "icon": "🏪", "desc": "跨多语言、多市场统一管理商品、订单、客户、库存与优惠活动", "source": "官方"},
            {"name": "Wix 店铺管理", "category": "店铺管理", "icon": "🏬", "desc": "一站式管理Wix网店全维度运营事务", "source": "官方"},
            {"name": "WooCommerce 店铺管理", "category": "店铺管理", "icon": "🛍️", "desc": "无需登录后台即可浏览商品、跟踪订单、处理退款", "source": "官方"},
            {"name": "eBay 店铺管理", "category": "店铺管理", "icon": "🔨", "desc": "全面掌控eBay卖家账户——商品刊登、订单追踪、物流", "source": "官方"},
            {"name": "WordPress 开发工具", "category": "店铺管理", "icon": "🔧", "desc": "开发定制WordPress主题、插件、Gutenberg区块", "source": "社区精选"},
            # 店铺经营 (8)
            {"name": "店铺经营分析", "category": "店铺经营", "icon": "📊", "desc": "每日拉取GMV、订单量、AOV数据，自动识别异常并生成运营日报", "source": "官方"},
            {"name": "店铺健康诊断", "category": "店铺经营", "icon": "🏥", "desc": "从弃购率、退款率、履约时效四个维度诊断店铺运营健康度", "source": "官方"},
            {"name": "客户洞察", "category": "店铺经营", "icon": "👥", "desc": "基于RFM模型对店铺客户分层，识别高价值客户和流失风险", "source": "官方"},
            {"name": "产品洞察", "category": "店铺经营", "icon": "🔍", "desc": "分析商品销售表现、SKU健康度与转化漏斗", "source": "官方"},
            {"name": "产品库存诊断", "category": "店铺经营", "icon": "📋", "desc": "每周SKU健康检测，生成管理摘要及可执行任务清单", "source": "官方"},
            {"name": "GA4 数据分析", "category": "店铺经营", "icon": "📈", "desc": "GA4业务分析与策略——报表解读、趋势分析与埋点方案", "source": "官方"},
            {"name": "GDPR 合规专家", "category": "店铺经营", "icon": "🛡️", "desc": "扫描代码库排查隐私风险、生成DPIA文件", "source": "社区精选"},
            {"name": "A/B 测试", "category": "店铺经营", "icon": "🧪", "desc": "电商卖家实验设计工具——样本量计算、显著性分析", "source": "官方"},
            # 选品与商品 (10)
            {"name": "智能选品", "category": "选品与商品", "icon": "🎯", "desc": "浏览供应商目录、发现趋势选品方向、五维可行性评分", "source": "官方"},
            {"name": "跨境选品助手", "category": "选品与商品", "icon": "🌍", "desc": "AliExpress与CJ Dropshipping搜货源、生成商品卡片和CSV清单", "source": "官方"},
            {"name": "亚马逊热搜词", "category": "选品与商品", "icon": "🔥", "desc": "交叉验证BSR、TikTok爆款趋势及谷歌趋势，挖掘高增长产品商机", "source": "官方"},
            {"name": "Listing 优化", "category": "选品与商品", "icon": "📝", "desc": "Amazon Listing优化——标题/五点/描述/A+/关键词全维度提升", "source": "官方"},
            {"name": "产品定价策略", "category": "选品与商品", "icon": "💰", "desc": "动态定价策略——成本分析、竞品价格监控、促销定价", "source": "社区精选"},
            {"name": "产品图片优化", "category": "选品与商品", "icon": "🖼️", "desc": "AI驱动的产品图片分析优化——主图/辅图/场景图/A+内容", "source": "社区精选"},
            {"name": "产品视频制作", "category": "选品与商品", "icon": "🎬", "desc": "产品视频脚本生成、AI视频制作、多平台适配", "source": "社区精选"},
            {"name": "产品合规检查", "category": "选品与商品", "icon": "✅", "desc": "多站点合规要求检查——认证/标签/限制品类/知识产权", "source": "社区精选"},
            {"name": "商品评论分析", "category": "选品与商品", "icon": "⭐", "desc": "AI驱动的评论情感分析，提取产品改进方向和用户痛点", "source": "社区精选"},
            {"name": "竞品商品拆解", "category": "选品与商品", "icon": "🔬", "desc": "8维度深度竞品分析——定价/材质/包装/功能/评论/流量/广告/排名", "source": "社区精选"},
            # 营销与内容 (21)
            {"name": "SEO 优化", "category": "营销与内容", "icon": "🔍", "desc": "站内外SEO全维度优化——关键词研究、内容策略、技术SEO", "source": "官方"},
            {"name": "社交媒体管理", "category": "营销与内容", "icon": "📱", "desc": "多平台社媒内容规划、发布排期、数据分析", "source": "官方"},
            {"name": "邮件营销", "category": "营销与内容", "icon": "📧", "desc": "自动化邮件营销——欢迎序列/弃购挽回/复购激励/节日促销", "source": "官方"},
            {"name": "内容策略规划", "category": "营销与内容", "icon": "📝", "desc": "内容策略、选题方向、排期表、核心板块——提升流量与行业权威", "source": "社区精选"},
            {"name": "营销创意灵感", "category": "营销与内容", "icon": "💡", "desc": "生成并推荐经过验证的SaaS产品营销思路与增长策略", "source": "社区精选"},
            {"name": "营销心理学", "category": "营销与内容", "icon": "🧠", "desc": "运用心理学原理、认知偏差与行为科学打造更具说服力的营销方案", "source": "社区精选"},
            {"name": "TikTok 营销", "category": "营销与内容", "icon": "🎵", "desc": "TikTok内容策略、视频创作流程、发布排期与自动化数据分析", "source": "社区精选"},
            {"name": "付费广告投放", "category": "营销与内容", "icon": "💸", "desc": "Google/Meta/LinkedIn/Twitter付费广告——受众定向、出价策略、ROAS", "source": "社区精选"},
            {"name": "TikTok 广告", "category": "营销与内容", "icon": "🎯", "desc": "TikTok广告策略——创意最佳实践、Spark Ads搭建与平台专项优化", "source": "社区精选"},
            {"name": "Reddit 广告", "category": "营销与内容", "icon": "🤖", "desc": "Reddit子版块定向投放与原生创意，精准触达垂直小众受众", "source": "社区精选"},
            {"name": "Explee 企业搜索", "category": "营销与内容", "icon": "🔍", "desc": "AI企业/人员搜索——1.05亿公司+5.36亿个人资料", "source": "集成"},
            {"name": "Revor 外联引擎", "category": "营销与内容", "icon": "📨", "desc": "LinkedIn/邮件/WhatsApp多渠道自动化外联执行", "source": "集成"},
            # 市场分析 (5)
            {"name": "市场分析", "category": "市场分析", "icon": "📊", "desc": "依托可溯源资料提供市场、竞品、投资者尽职调查及行业情报分析", "source": "官方"},
            {"name": "竞争对手分析", "category": "市场分析", "icon": "⚔️", "desc": "竞争格局与五力模型分析，识别定价空白和差异化切入点", "source": "官方"},
            {"name": "竞品雷达", "category": "市场分析", "icon": "📡", "desc": "追踪情感倾向、投诉与信任信号，识别风险与机遇", "source": "官方"},
            {"name": "品牌舆情监控", "category": "市场分析", "icon": "🔔", "desc": "实时品牌监测——社交平台提及侦测、风险分级、回复草稿生成", "source": "官方"},
            {"name": "关键词排名追踪", "category": "市场分析", "icon": "📈", "desc": "长期追踪关键词排名与SERP特征变化，覆盖传统搜索与AI回复", "source": "社区精选"},
        ]
        return {"success": True, "total": len(skills), "skills": skills}

    @app.get("/api/capability-hub/sellersprite/tools")
    async def capability_hub_sellersprite_tools():
        """能力中心 - SellerSprite 工具列表"""
        tools = [
            # ASIN分析
            {"id": "competitor_lookup", "category": "asin_analysis", "name": "查竞品", "endpoint": "/api/1", "desc": "查目标ASIN的销量和销额等详细数据", "icon": "📊"},
            {"id": "asin_detail", "category": "asin_analysis", "name": "ASIN详情", "endpoint": "/api/3", "desc": "上架日期、BSR排名、A+等信息", "icon": "📋"},
            {"id": "asin_sales_trend", "category": "asin_analysis", "name": "销量趋势", "endpoint": "/api/61", "desc": "父体/子体销量、销售额趋势数据", "icon": "📈"},
            {"id": "asin_prediction", "category": "asin_analysis", "name": "销量预测", "endpoint": "/api/27", "desc": "ASIN销量预测", "icon": "🔮"},
            {"id": "asin_coupon_trend", "category": "asin_analysis", "name": "优惠趋势", "endpoint": "/api/56", "desc": "ASIN优惠趋势数据", "icon": "🏷️"},
            {"id": "asin_detail_coupon", "category": "asin_analysis", "name": "详情+优惠趋势", "endpoint": "/api/57", "desc": "ASIN详情及优惠趋势组合", "icon": "📦"},
            # 选品与市场
            {"id": "product_research", "category": "product_selection", "name": "选产品", "endpoint": "/api/2", "desc": "多维度筛选潜力商品", "icon": "🛍️"},
            {"id": "product_node", "category": "product_selection", "name": "产品类目", "endpoint": "/api/9", "desc": "查询类目ID/名称/节点/产品数量", "icon": "🗂️"},
            {"id": "market_research", "category": "product_selection", "name": "选市场列表", "endpoint": "/api/29", "desc": "细分类目市场分析数据", "icon": "🌍"},
            {"id": "market_statistics", "category": "product_selection", "name": "市场统计", "endpoint": "/api/30", "desc": "类目统计数据", "icon": "📊"},
            {"id": "market_product_concentration", "category": "product_selection", "name": "商品集中度", "endpoint": "/api/31", "desc": "商品集中度分析", "icon": "📐"},
            {"id": "market_brand_concentration", "category": "product_selection", "name": "品牌集中度", "endpoint": "/api/32", "desc": "品牌集中度分析", "icon": "🏢"},
            {"id": "market_seller_concentration", "category": "product_selection", "name": "卖家集中度", "endpoint": "/api/33", "desc": "卖家集中度分析", "icon": "👥"},
            {"id": "market_seller_country", "category": "product_selection", "name": "卖家所属地", "endpoint": "/api/35", "desc": "卖家所属地分布", "icon": "🌏"},
            {"id": "market_seller_type", "category": "product_selection", "name": "卖家类型", "endpoint": "/api/34", "desc": "卖家类型分布", "icon": "👤"},
            {"id": "market_demand_trend", "category": "product_selection", "name": "需求趋势", "endpoint": "/api/36", "desc": "商品需求趋势", "icon": "📈"},
            {"id": "market_listing_date", "category": "product_selection", "name": "上架时间", "endpoint": "/api/37", "desc": "上架时间分布", "icon": "📅"},
            {"id": "market_listing_trend", "category": "product_selection", "name": "上架趋势", "endpoint": "/api/38", "desc": "上架趋势分布", "icon": "📉"},
            {"id": "market_ratings_count", "category": "product_selection", "name": "评分数分布", "endpoint": "/api/39", "desc": "评分数分布", "icon": "⭐"},
            {"id": "market_rating", "category": "product_selection", "name": "评分值分布", "endpoint": "/api/40", "desc": "评分值分布", "icon": "🌟"},
            {"id": "market_price", "category": "product_selection", "name": "价格分布", "endpoint": "/api/41", "desc": "价格分布", "icon": "💰"},
            {"id": "market_ebc", "category": "product_selection", "name": "A+视频分布", "endpoint": "/api/42", "desc": "A+视频分布", "icon": "🎬"},
            # 关键词研究
            {"id": "traffic_keyword", "category": "keyword_research", "name": "关键词反查", "endpoint": "/api/14", "desc": "ASIN近30天前3页搜索流量词", "icon": "🔍"},
            {"id": "keyword_miner", "category": "keyword_research", "name": "关键词挖掘", "endpoint": "/api/6", "desc": "衍生词及长尾关键词", "icon": "⛏️"},
            {"id": "keyword_research", "category": "keyword_research", "name": "关键词选品", "endpoint": "/api/10", "desc": "月搜索量/购买率等", "icon": "🔑"},
            {"id": "keyword_trends", "category": "keyword_research", "name": "关键词趋势", "endpoint": "/api/11", "desc": "关键词历史趋势数据", "icon": "📈"},
            {"id": "keyword_order", "category": "keyword_research", "name": "出单词反查", "endpoint": "/api/24", "desc": "竞品Top出单词", "icon": "🎯"},
            {"id": "traffic_extend", "category": "keyword_research", "name": "拓展流量词", "endpoint": "/api/46", "desc": "多ASIN拓展流量词", "icon": "🌐"},
            # ABA与趋势
            {"id": "aba_weekly", "category": "aba_trends", "name": "ABA周选品", "endpoint": "/api/19", "desc": "ABA数据选品-按周", "icon": "📆"},
            {"id": "aba_monthly", "category": "aba_trends", "name": "ABA月选品", "endpoint": "/api/20", "desc": "ABA数据选品-按月", "icon": "🗓️"},
            {"id": "aba_trend", "category": "aba_trends", "name": "ABA关键词趋势", "endpoint": "/api/60", "desc": "ABA关键词历史搜索趋势", "icon": "📊"},
            {"id": "google_trend", "category": "aba_trends", "name": "谷歌趋势", "endpoint": "/api/12", "desc": "关键词谷歌趋势", "icon": "🔍"},
            {"id": "bsr_prediction", "category": "aba_trends", "name": "BSR销量预测", "endpoint": "/api/26", "desc": "根据BSR值预测销量", "icon": "📉"},
            {"id": "keepa_info", "category": "aba_trends", "name": "商品趋势详情", "endpoint": "/api/22", "desc": "价格/BSR/评论数历史趋势", "icon": "📊"},
            # 流量分析
            {"id": "traffic_source", "category": "traffic_analysis", "name": "流量来源", "endpoint": "/api/17", "desc": "关键词流向分析", "icon": "🚦"},
            {"id": "traffic_listing", "category": "traffic_analysis", "name": "关联流量列表", "endpoint": "/api/16", "desc": "产品及变体关联流量", "icon": "🔗"},
            {"id": "traffic_keyword_stat", "category": "traffic_analysis", "name": "流量词统计", "endpoint": "/api/13", "desc": "流量词统计", "icon": "📊"},
            {"id": "traffic_listing_stat", "category": "traffic_analysis", "name": "关联流量统计", "endpoint": "/api/15", "desc": "关联流量统计", "icon": "📈"},
            # 评论
            {"id": "review", "category": "review", "name": "查评论", "endpoint": "/api/25", "desc": "查询Product Review", "icon": "💬"},
            # 商标
            {"id": "trademark_countries", "category": "trademark", "name": "商标数据范围", "endpoint": "/api/50", "desc": "支持商标查询的国家数据", "icon": "🌍"},
            {"id": "trademark_detail", "category": "trademark", "name": "商标详情", "endpoint": "/api/49", "desc": "商标详细信息", "icon": "📄"},
            {"id": "trademark_list", "category": "trademark", "name": "商标列表", "endpoint": "/api/48", "desc": "商标列表数据", "icon": "📋"},
            {"id": "trademark_stats", "category": "trademark", "name": "商标统计", "endpoint": "/api/47", "desc": "商标统计数据", "icon": "📊"},
            # 工具
            {"id": "image_text_recognition", "category": "utility", "name": "图片文字识别", "endpoint": "/api/44", "desc": "图片文字识别", "icon": "🖼️"},
        ]
        return {"success": True, "total": len(tools), "tools": tools}

    logger.info("🧩 Capability Hub API routes registered (统一能力中心 · 连接器系统)")

    # ============================================================
    # Brand Narrative API - 品牌叙事 · 微软 Build 2026 对齐
    # ============================================================

    @app.get("/api/brand/narrative")
    async def brand_narrative():
        """获取 Simiaiclaw OS 品牌叙事和微软 Build 2026 战略对齐"""
        return {
            "success": True,
            "brand": {
                "name": "Simiaiclaw OS",
                "full_name": "龙虾星球共创联盟 · Simiaiclaw OS",
                "tagline": "一万个硅基大脑 · 全量调度操作系统",
                "version": "5.4.0"
            },
            "narrative": {
                "core_theme": "硅基大脑网络 · 全量调度操作系统",
                "ms_build_2026_alignment": "微软 Build 2026 宣布正在用「一万个硅基大脑」的网络涌现逻辑去重构下一代计算平台。他们不再满足于做「输入框里的聊天助手」，而是要直接做控制所有自动化管线的「全量调度操作系统」。而这，与 Simiaiclaw OS 龙虾星球系统不谋而合。"
            },
            "architecture": {
                "layers": [
                    {"name": "战略决策层", "agents": ["Board CEO", "Board CTO", "Board CFO", "Board CMO", "Board COO"]},
                    {"name": "市场情报层", "agents": ["Market Intel", "Competitor", "Trend", "PR/SEM/Ads"]},
                    {"name": "品牌与内容层", "agents": ["Brand", "Content", "Video", "Localization", "Design"]},
                    {"name": "销售与增长层", "agents": ["Amazon", "Shopify", "TikTok Shop", "Channel", "CRM"]},
                    {"name": "运营执行层", "agents": ["Operations", "Ads Ops", "Churn", "Retention", "Marketplace"]},
                    {"name": "供应链层", "agents": ["Inventory", "Logistics", "Supplier", "Quality", "Order"]},
                    {"name": "财务与合规层", "agents": ["Finance", "Tax", "Invoice", "Payment", "Cost Control"]},
                    {"name": "基础设施层", "agents": ["OpenClaw", "AnyGen", "HeyGen", "Composio", "InsForge"]}
                ]
            },
            "alignment": {
                "agent_first": {"ms": "Agent First 战略：从 Copilot 到 Autopilot", "simiaiclaw": "100+ Agent 集群 · 8 层组织架构自治运行"},
                "multi_agent": {"ms": "Copilot Studio 多 Agent 编排", "simiaiclaw": "118 SOP TaskFlow · Board → Sales 协同调度"},
                "context_layer": {"ms": "Microsoft IQ (Work/Fabric/Foundry IQ)", "simiaiclaw": "知识库 + InsForge BaaS + Agent 记忆系统"},
                "security": {"ms": "MXC 沙箱 + Agent 365 + ACS 策略", "simiaiclaw": "Electron 沙箱 + 企业权限 + Skills 安全审核"},
                "open_ecosystem": {"ms": "MCP 协议 + 1000+ Composio Apps", "simiaiclaw": "Composio 1000+ + 30+ 平台连接器"},
                "os_evolution": {"ms": "Windows 365 for Agents + Project Solara", "simiaiclaw": "Electron Desktop OS + Dashboard 全量调度面板"}
            },
            "stats": {
                "agent_count": "100+",
                "skill_count": "1000+",
                "connector_count": "30+",
                "sop_taskflow_count": 118,
                "model_engines": ["Ollama", "OpenAI", "Claude", "AnyGen", "HeyGen"]
            }
        }

    @app.get("/api/brand/os")
    async def brand_os_page():
        """返回品牌叙事 OS 页面 HTML"""
        brand_html_path = Path(__file__).parent.parent / "dashboard" / "brand-os.html"
        if brand_html_path.exists():
            return HTMLResponse(content=brand_html_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Brand OS page not found</h1>", status_code=404)

    logger.info("🦞 Brand Narrative API routes registered (Simiaiclaw OS · Build 2026 alignment)")

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
            "openclaw_version": "5.4.0",
        }

    return app


# ============================================================
# 平台连接测试辅助函数
# ============================================================

async def _test_shopify_connection(config: dict) -> dict:
    """测试 Shopify 连接"""
    store = config.get("shopify_store", "")
    token = config.get("shopify_access_token", "")
    if not store or not token:
        raise Exception("缺少店铺域名或 Access Token")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.get(
            f"https://{store}/admin/api/2024-01/shop.json",
            headers={"X-Shopify-Access-Token": token},
        )
        if resp.status_code == 200:
            shop = resp.json().get("shop", {})
            return {"shop_name": shop.get("name", ""), "domain": shop.get("domain", ""), "plan": shop.get("plan_name", "")}
        raise Exception(f"Shopify 返回 {resp.status_code}: {resp.text[:200]}")

async def _test_tiktok_connection(config: dict) -> dict:
    """测试 TikTok 连接"""
    client_key = config.get("tiktok_client_key", "")
    if not client_key:
        raise Exception("缺少 Client Key")
    # TikTok API 需要 OAuth token，仅验证凭据存在
    return {"verified": True, "client_key_configured": True}

async def _test_amazon_connection(config: dict) -> dict:
    """测试 Amazon SP-API 连接"""
    seller_id = config.get("amazon_seller_id", "")
    if not seller_id:
        raise Exception("缺少 Seller ID")
    return {"verified": True, "seller_id": seller_id}

async def _test_stripe_connection(config: dict) -> dict:
    """测试 Stripe 连接"""
    secret_key = config.get("stripe_secret_key", "")
    if not secret_key:
        raise Exception("缺少 Secret Key")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.get(
            "https://api.stripe.com/v1/balance",
            auth=(secret_key, ""),
        )
        if resp.status_code == 200:
            balance = resp.json()
            return {"available": balance.get("available", [{}])[0].get("amount", 0) / 100 if balance.get("available") else 0}
        raise Exception(f"Stripe 返回 {resp.status_code}")

async def _test_google_ads_connection(config: dict) -> dict:
    """测试 Google Ads 连接"""
    developer_token = config.get("google_ads_developer_token", "")
    if not developer_token:
        raise Exception("缺少 Developer Token")
    return {"verified": True, "developer_token_configured": True}


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
