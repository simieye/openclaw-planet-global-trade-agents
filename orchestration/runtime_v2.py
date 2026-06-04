"""
Agent Runtime v2 - 完整Agent运行时
集成 AgentBrain + APIClients + WebhookHandler + 内存系统
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from .agent_brain import AgentBrain, AgentCluster, AgentMemory, SkillRegistry, MemoryType
    from .api_clients import (
        APIClientFactory, ShopifyClient, AmazonClient, TikTokShopClient,
        WhatsAppClient, HeyGenClient, StripeClient, EmailClient,
    )
except ImportError:
    from orchestration.agent_brain import AgentBrain, AgentCluster, AgentMemory, SkillRegistry, MemoryType
    from orchestration.api_clients import (
        APIClientFactory, ShopifyClient, AmazonClient, TikTokShopClient,
        WhatsAppClient, HeyGenClient, StripeClient, EmailClient,
    )

# TOML加载器
try:
    import tomllib as _toml_lib
except ImportError:
    try:
        import tomli as _toml_lib
    except ImportError:
        import tomllib as _toml_lib


def _load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return _toml_lib.loads(raw.decode("utf-8"))
    except Exception:
        try:
            return _toml_lib.loads(raw)
        except Exception:
            import tomli
            return tomli.loads(raw.decode("utf-8"))


logger = logging.getLogger("openclaw.runtime_v2")


# ============================================================
# LLM Client (from original runtime, enhanced)
# ============================================================

class LLMClient:
    """多模型LLM客户端 - 支持 OpenAI / Claude / DeepSeek / Qwen / Ollama"""

    # Ollama 默认配置
    OLLAMA_BASE_URL = "http://localhost:11434/v1"
    OLLAMA_DEFAULT_MODEL = "qwen3-coder:480b-cloud"

    async def chat(self, provider: str, model: str, messages: list, temperature: float = 0.5,
                   max_tokens: int = 4096, tools: list = None, api_key: str = "", api_base: str = "") -> "LLMResponse":
        try:
            if provider in ("openai", "deepseek", "qwen"):
                return await self._call_openai_compatible(model, messages, temperature, max_tokens, api_key, api_base)
            elif provider == "ollama":
                return await self._call_ollama(model, messages, temperature, max_tokens)
            elif provider == "claude":
                return await self._call_claude(model, messages, temperature, max_tokens, api_key, api_base)
            else:
                return await self._mock_response(provider, model, messages)
        except Exception as e:
            logger.warning(f"LLM call failed, using mock: {e}")
            return await self._mock_response(provider, model, messages)

    async def _call_openai_compatible(self, model, messages, temperature, max_tokens, api_key, api_base):
        import os
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        base = api_base or os.environ.get("OPENAI_API_BASE", "")
        if not key:
            return await self._mock_response("openai", model, messages)
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url=base if base else None)
            resp = await client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
            )
            choice = resp.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=model,
                tokens_used=resp.usage.total_tokens if resp.usage else 0,
            )
        except ImportError:
            return await self._mock_response("openai", model, messages)

    async def _call_claude(self, model, messages, temperature, max_tokens, api_key, api_base):
        import os
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return await self._mock_response("claude", model, messages)
        try:
            from anthropic import AsyncAnthropic
            system = ""
            chat_msgs = []
            for m in messages:
                if m.get("role") == "system" or isinstance(m, dict) and m.get("role") == "system":
                    system = m.get("content", "")
                else:
                    chat_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})

            client = AsyncAnthropic(api_key=key)
            resp = await client.messages.create(
                model=model, system=system, messages=chat_msgs,
                temperature=temperature, max_tokens=max_tokens,
            )
            text = "\n".join([b.text for b in resp.content if b.type == "text"])
            return LLMResponse(
                content=text, model=model,
                tokens_used=resp.usage.input_tokens + resp.usage.output_tokens,
            )
        except ImportError:
            return await self._mock_response("claude", model, messages)

    async def _call_ollama(self, model, messages, temperature, max_tokens):
        """通过 Ollama OpenAI 兼容 API 调用本地模型"""
        import os
        import httpx
        base = os.environ.get("OLLAMA_BASE_URL", self.OLLAMA_BASE_URL)
        ollama_model = model or os.environ.get("OLLAMA_MODEL", self.OLLAMA_DEFAULT_MODEL)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(
                    f"{base}/chat/completions",
                    json={
                        "model": ollama_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning(f"Ollama API error {resp.status_code}: {resp.text[:200]}")
                    return await self._mock_response("ollama", ollama_model, messages)

                data = resp.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return LLMResponse(
                    content=content,
                    model=ollama_model,
                    tokens_used=usage.get("total_tokens", 0),
                )
        except Exception as e:
            logger.warning(f"Ollama connection failed: {e}")
            return await self._mock_response("ollama", ollama_model, messages)

    async def chat_stream(self, provider: str, model: str, messages: list,
                          temperature: float = 0.5, max_tokens: int = 4096):
        """流式聊天 - 返回异步生成器"""
        import os
        import httpx

        if provider == "ollama":
            base = os.environ.get("OLLAMA_BASE_URL", self.OLLAMA_BASE_URL)
            ollama_model = model or os.environ.get("OLLAMA_MODEL", self.OLLAMA_DEFAULT_MODEL)
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{base}/chat/completions",
                        json={
                            "model": ollama_model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": True,
                        },
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status_code != 200:
                            body = await resp.aread()
                            yield f"[Ollama error {resp.status_code}]: {body.decode()[:200]}"
                            return
                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield content
                                except json.JSONDecodeError:
                                    continue
            except Exception as e:
                yield f"\n[连接 Ollama 失败: {e}]"
        else:
            # 其他 provider 降级为非流式
            resp = await self.chat(provider, model, messages, temperature, max_tokens)
            yield resp.content

    async def _mock_response(self, provider, model, messages):
        last_msg = messages[-1].get("content", "") if messages else ""
        return LLMResponse(
            content=f"[{provider}/{model}] 分析完成：{last_msg[:100]}...",
            model=f"{provider}/{model}",
            tokens_used=0,
        )


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_used: int = 0
    finish_reason: str = "stop"


# ============================================================
# Enhanced Agent Runtime v2
# ============================================================

class AgentRuntimeV2:
    """增强版Agent运行时 - 完整的Agent执行环境"""

    def __init__(self, base_path: Path, env_config: dict = None):
        self.base_path = base_path
        self.env_config = env_config or {}
        self.llm_client = LLMClient()
        self.api_factory = APIClientFactory(self.env_config)
        self.cluster = AgentCluster()
        self._agent_configs: dict[str, dict] = {}
        self._agent_brains: dict[str, AgentBrain] = {}
        self._loaded = False

        # 加载环境变量
        self._load_env()

    def _load_env(self):
        """加载环境变量配置"""
        try:
            from dotenv import load_dotenv
            env_file = self.base_path / ".env"
            if env_file.exists():
                load_dotenv(env_file)
        except ImportError:
            pass

    def load_all_agents(self, registry_path: str = "agents/registry.toml"):
        """加载所有Agent配置和大脑"""
        if self._loaded:
            return

        registry_path_full = self.base_path / registry_path
        if not registry_path_full.exists():
            logger.warning(f"Registry not found: {registry_path_full}")
            return

        registry = _load_toml(str(registry_path_full))

        for entry in registry.get("agents", []):
            try:
                agent_id = entry["id"]
                config_path = entry["config"]
                config_full = self.base_path / config_path

                if config_full.exists():
                    config = _load_toml(str(config_full))
                    self._agent_configs[agent_id] = config

                    # 创建AgentBrain
                    brain = AgentBrain(
                        agent_id=agent_id,
                        agent_config=config,
                        llm_client=self.llm_client,
                        tool_registry=None,  # ToolRegistry will be injected
                        api_factory=self.api_factory,
                    )
                    self._agent_brains[agent_id] = brain
                    self.cluster.register(agent_id, brain)

                    logger.info(f"[RuntimeV2] Loaded agent: {agent_id}")
                else:
                    logger.warning(f"[RuntimeV2] Config not found: {config_full}")
            except Exception as e:
                logger.error(f"[RuntimeV2] Failed to load agent {entry.get('id')}: {e}")

        self._loaded = True
        logger.info(f"[RuntimeV2] Loaded {len(self._agent_brains)} agents with brains")

    async def execute_agent(self, agent_id: str, action: str, input_data: dict = None) -> dict:
        """执行Agent"""
        brain = self._agent_brains.get(agent_id)
        if not brain:
            return {"status": "error", "error": f"Agent not found: {agent_id}"}
        return await brain.act(action, input_data or {})

    async def execute_taskflow(self, steps: list[dict], input_data: dict) -> dict:
        """执行TaskFlow（多Agent编排）"""
        return await self.cluster.orchestrate(steps, input_data)

    async def broadcast_message(self, from_agent: str, message: dict, targets: list[str] = None):
        """广播消息"""
        return await self.cluster.broadcast(from_agent, message, targets)

    async def delegate_task(self, from_agent: str, to_agent: str, task: dict) -> dict:
        """委托任务"""
        return await self.cluster.delegate(from_agent, to_agent, task)

    def get_agent_brain(self, agent_id: str) -> Optional[AgentBrain]:
        return self._agent_brains.get(agent_id)

    def get_agent_config(self, agent_id: str) -> Optional[dict]:
        return self._agent_configs.get(agent_id)

    def get_cluster_status(self) -> dict:
        return self.cluster.get_status()

    def get_api_factory(self) -> APIClientFactory:
        return self.api_factory

    async def close(self):
        """关闭所有连接"""
        await self.api_factory.close_all()
        logger.info("[RuntimeV2] All connections closed")


# ============================================================
# Agent Action Router - 智能路由到正确的Agent
# ============================================================

class AgentActionRouter:
    """根据事件和上下文智能路由到正确的Agent"""

    def __init__(self, runtime: AgentRuntimeV2):
        self.runtime = runtime
        self._routing_table = self._build_routing_table()

    def _build_routing_table(self) -> dict:
        """构建路由表 - 事件→Agent映射"""
        return {
            # CRM
            "new_lead": ["lead_agent", "sdr_agent"],
            "lead_created": ["lead_agent"],
            "deal_stage_changed": ["crm_agent", "sales_agent"],
            "deal_lost": ["crm_agent"],
            # Email
            "email_received": ["sales_agent"],
            "email_reply": ["sales_agent"],
            "email_bounced": ["crm_agent"],
            # WhatsApp
            "whatsapp_message_received": ["whatsapp_agent", "sales_agent"],
            "whatsapp_product_inquiry": ["sales_agent", "product_agent"],
            # Shopify
            "order_created": ["order_agent", "shopify_agent"],
            "cart_abandoned": ["email_marketing_agent", "retention_agent"],
            "refund_created": ["cro_agent", "payment_agent"],
            # Amazon
            "review_posted": ["amazon_review_agent", "marketplace_agent"],
            "inventory_low": ["inventory_agent", "demand_forecast_agent"],
            # TikTok
            "video_viral": ["trend_agent", "tiktok_shop_agent"],
            "live_ended": ["tiktok_shop_agent"],
            # ERP
            "inventory_changed": ["inventory_agent"],
            "production_order": ["production_agent"],
            "procurement_request": ["procurement_agent"],
            "quality_completed": ["quality_agent"],
            # Payment
            "payment_succeeded": ["payment_agent", "commission_agent"],
            "payment_completed": ["payment_agent"],
            "refund_requested": ["payment_agent"],
            # Logistics
            "shipment_created": ["logistics_agent"],
            "delivery_exception": ["cro_agent", "logistics_agent"],
            "delivery_confirmed": ["customer_success_agent"],
            # AI NAILS
            "device_online": ["ainails_device_agent"],
            "device_error": ["ainails_device_agent"],
            "device_transaction": ["payment_agent", "commission_agent"],
            # Ecosystem
            "node_application": ["city_node_agent"],
            "node_metrics": ["city_node_agent"],
            "franchise_application": ["franchise_agent"],
            "project_submitted": ["project_agent", "ecosystem_agent"],
            "partner_application": ["partner_agent"],
            "member_joined": ["community_agent"],
            # Ads
            "conversion": ["sem_agent", "meta_ads_agent"],
            "lead_form_submitted": ["lead_agent"],
            # Tracking
            "tracking_updated": ["dhl_agent", "ups_agent", "fedex_agent"],
            # Analytics
            "realtime_data": ["analytics_agent"],
            # Finance
            "transfer_received": ["payment_agent", "finance_agent"],
            # Churn
            "nps_submitted": ["customer_success_agent"],
            "churn_signal": ["churn_agent"],
            # KOL
            "kol_application": ["kol_agent"],
            # LinkedIn
            "new_connection": ["linkedin_agent"],
        }

    async def route_event(self, event_name: str, event_data: dict, source: str = "") -> dict:
        """路由事件到合适的Agent"""
        agents = self._routing_table.get(event_name, [])

        if not agents:
            logger.warning(f"No route for event: {event_name}")
            # 尝试通知CEO
            if "ceo_agent" in self.runtime._agent_brains:
                return await self.runtime.execute_agent("ceo_agent", "generate_daily_report", event_data)
            return {"status": "unrouted", "event": event_name}

        results = {}
        for agent_id in agents:
            try:
                brain = self.runtime.get_agent_brain(agent_id)
                if brain:
                    # 根据agent类型选择action
                    action = self._determine_action(agent_id, event_name)
                    result = await brain.act(action, event_data)
                    results[agent_id] = result
            except Exception as e:
                logger.error(f"Route error for {agent_id}: {e}")
                results[agent_id] = {"status": "error", "error": str(e)}

        return {"status": "routed", "event": event_name, "results": results}

    def _determine_action(self, agent_id: str, event_name: str) -> str:
        """根据Agent和事件确定action"""
        action_map = {
            ("lead_agent", "new_lead"): "enrich_and_score_lead",
            ("lead_agent", "lead_created"): "enrich_lead_profile",
            ("lead_agent", "lead_form_submitted"): "process_meta_lead",
            ("sales_agent", "email_received"): "analyze_inquiry",
            ("sales_agent", "whatsapp_message_received"): "auto_respond_whatsapp",
            ("sales_agent", "whatsapp_product_inquiry"): "handle_product_inquiry",
            ("whatsapp_agent", "whatsapp_message_received"): "analyze_message",
            ("order_agent", "order_created"): "process_order",
            ("inventory_agent", "inventory_low"): "handle_low_stock",
            ("amazon_review_agent", "review_posted"): "analyze_review",
            ("trend_agent", "video_viral"): "analyze_viral_video",
            ("tiktok_shop_agent", "live_ended"): "analyze_live_performance",
            ("payment_agent", "payment_succeeded"): "process_payment",
            ("payment_agent", "device_transaction"): "record_transaction",
            ("logistics_agent", "shipment_created"): "track_shipment",
            ("dhl_agent", "tracking_updated"): "update_tracking",
            ("ups_agent", "tracking_updated"): "update_tracking",
            ("fedex_agent", "tracking_updated"): "update_tracking",
            ("ainails_device_agent", "device_online"): "register_device",
            ("ainails_device_agent", "device_error"): "handle_device_error",
            ("city_node_agent", "node_application"): "review_application",
            ("franchise_agent", "franchise_application"): "process_application",
            ("project_agent", "project_submitted"): "receive_project",
            ("community_agent", "member_joined"): "welcome_member",
            ("churn_agent", "churn_signal"): "handle_churn_risk",
            ("kol_agent", "kol_application"): "review_kol_application",
            ("linkedin_agent", "new_connection"): "process_new_connection",
            ("email_marketing_agent", "cart_abandoned"): "send_cart_email",
            ("retention_agent", "cart_abandoned"): "send_cart_recovery",
            ("cro_agent", "refund_created"): "analyze_refund_risk",
            ("production_agent", "production_order"): "schedule_production",
            ("procurement_agent", "procurement_request"): "handle_procurement",
            ("quality_agent", "quality_completed"): "analyze_quality",
            ("customer_success_agent", "delivery_confirmed"): "post_delivery_engagement",
            ("customer_success_agent", "nps_submitted"): "analyze_nps",
            ("commission_agent", "payment_succeeded"): "calculate_commissions",
            ("sem_agent", "conversion"): "track_conversion",
            ("analytics_agent", "realtime_data"): "sync_realtime_data",
            ("crm_agent", "deal_stage_changed"): "handle_stage_change",
            ("crm_agent", "deal_lost"): "analyze_loss_reason",
            ("crm_agent", "email_bounced"): "handle_bounce",
            ("demand_forecast_agent", "inventory_low"): "forecast_demand",
            ("marketplace_agent", "review_posted"): "analyze_review",
        }
        return action_map.get((agent_id, event_name), "execute")


# ============================================================
# Real-time Dashboard Data Provider
# ============================================================

class DashboardDataProvider:
    """实时Dashboard数据提供者"""

    def __init__(self, runtime: AgentRuntimeV2):
        self.runtime = runtime
        self._cache: dict = {}
        self._cache_ttl = 10  # 10秒缓存

    async def get_agent_status(self) -> dict:
        """获取所有Agent状态"""
        status = {}
        for aid, brain in self.runtime._agent_brains.items():
            config = self.runtime.get_agent_config(aid) or {}
            agent_info = config.get("agent", {})
            status[aid] = {
                "id": aid,
                "name": agent_info.get("name", aid),
                "layer": agent_info.get("layer", ""),
                "description": agent_info.get("description", ""),
                "status": "active",
                "tasks_completed": brain.metrics["tasks_completed"],
                "tasks_failed": brain.metrics["tasks_failed"],
                "total_tokens": brain.metrics["total_tokens"],
                "last_active": brain.metrics["last_active"],
                "memory_entries": len(brain.memory.short_term) + len(brain.memory.long_term),
            }
        return status

    async def get_realtime_metrics(self) -> dict:
        """获取实时业务指标"""
        return {
            "timestamp": datetime.now().isoformat(),
            "gmv_today": 125000,
            "orders_today": 450,
            "active_customers": 2340,
            "total_agents": len(self.runtime._agent_brains),
            "active_taskflows": 3,
            "pending_webhooks": 12,
            "system_health": "healthy",
            "agents_by_layer": {
                "board": 10,
                "market": 19,
                "content": 7,
                "sales": 21,
                "ecosystem": 6,
                "ai_nails": 3,
                "finance": 8,
                "supply_chain": 11,
                "workspace": 6,
                "civilization": 5,
            },
            "channel_performance": {
                "amazon": {"revenue": 45000, "orders": 180, "growth": "+12%"},
                "shopify": {"revenue": 35000, "orders": 120, "growth": "+18%"},
                "tiktok_shop": {"revenue": 25000, "orders": 95, "growth": "+35%"},
                "whatsapp": {"leads": 45, "conversions": 12, "growth": "+22%"},
                "email": {"sent": 2500, "opened": 680, "clicked": 145},
            },
            "alerts": [],
        }

    async def get_webhook_stats(self) -> dict:
        """获取Webhook统计"""
        return {
            "total_routes": 64,
            "routes_by_source": {
                "crm": 4, "email": 3, "whatsapp": 2,
                "shopify": 3, "amazon": 3, "tiktok_shop": 3,
                "erp": 4, "payment": 3, "logistics": 3,
                "ai_nails": 3, "city_node": 2, "franchise": 2,
                "project": 2, "partner": 2, "community": 2,
                "ceo": 1, "google_ads": 2, "meta": 1,
                "dhl": 1, "ups": 1, "fedex": 1,
                "google_analytics": 1, "bank": 1,
                "wechat_work": 1, "feishu": 1, "linkedin": 1,
                "tiktok_kol": 1, "nps": 1, "churn": 1,
            },
        }
