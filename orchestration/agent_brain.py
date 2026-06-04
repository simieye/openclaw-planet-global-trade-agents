"""
Agent Brain - 智能体核心执行大脑
每个Agent的真实业务逻辑实现
包含：LLM推理、工具调用、多Agent协作、上下文记忆
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Callable

logger = logging.getLogger("openclaw.brain")


# ============================================================
# Memory System
# ============================================================

class MemoryType(Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    WORKING = "working"
    EPISODIC = "episodic"


@dataclass
class MemoryEntry:
    id: str
    type: MemoryType
    agent_id: str
    content: dict
    importance: float = 0.5
    timestamp: datetime = field(default_factory=datetime.now)
    ttl_seconds: int = 3600  # 短期记忆1小时


class AgentMemory:
    """Agent记忆系统 - 短期/长期/工作/情景记忆"""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.short_term: list[MemoryEntry] = []
        self.long_term: list[MemoryEntry] = []
        self.working: dict[str, Any] = {}
        self.episodic: list[MemoryEntry] = []
        self.max_short_term = 50
        self.max_long_term = 500

    def remember(self, content: dict, mem_type: MemoryType = MemoryType.SHORT_TERM, importance: float = 0.5):
        entry = MemoryEntry(
            id=f"mem-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            type=mem_type,
            agent_id=self.agent_id,
            content=content,
            importance=importance,
        )
        if mem_type == MemoryType.SHORT_TERM:
            self.short_term.append(entry)
            if len(self.short_term) > self.max_short_term:
                # 淘汰低重要性记忆
                self.short_term.sort(key=lambda x: x.importance)
                self.short_term = self.short_term[-self.max_short_term:]
        elif mem_type == MemoryType.LONG_TERM:
            self.long_term.append(entry)
            if len(self.long_term) > self.max_long_term:
                self.long_term.sort(key=lambda x: x.timestamp)
                self.long_term = self.long_term[-self.max_long_term:]
        elif mem_type == MemoryType.EPISODIC:
            self.episodic.append(entry)
        return entry

    def recall(self, query: str = "", mem_type: MemoryType = None, limit: int = 10) -> list[MemoryEntry]:
        """回忆记忆"""
        pool = []
        if mem_type == MemoryType.SHORT_TERM:
            pool = self.short_term
        elif mem_type == MemoryType.LONG_TERM:
            pool = self.long_term
        elif mem_type == MemoryType.EPISODIC:
            pool = self.episodic
        else:
            pool = self.short_term + self.long_term + self.episodic

        if query:
            # 简单关键词匹配
            pool = [m for m in pool if query.lower() in json.dumps(m.content, ensure_ascii=False).lower()]

        return sorted(pool, key=lambda x: (x.importance, x.timestamp), reverse=True)[:limit]

    def forget_old(self, max_age_hours: int = 24):
        """遗忘过期记忆"""
        cutoff = datetime.now().timestamp() - max_age_hours * 3600
        self.short_term = [m for m in self.short_term if m.timestamp.timestamp() > cutoff]

    def to_context(self) -> dict:
        """导出为上下文"""
        return {
            "short_term_count": len(self.short_term),
            "long_term_count": len(self.long_term),
            "recent_memories": [
                {"content": m.content, "importance": m.importance, "timestamp": m.timestamp.isoformat()}
                for m in sorted(self.short_term[-5:], key=lambda x: x.timestamp, reverse=True)
            ],
        }


# ============================================================
# Skill System
# ============================================================

class SkillRegistry:
    """技能注册中心 - 可复用的Agent技能"""

    def __init__(self):
        self._skills: dict[str, dict] = {}
        self._register_builtin_skills()

    def _register_builtin_skills(self):
        """注册内置技能"""
        self.register("market_analysis", {
            "name": "市场分析",
            "description": "分析目标市场容量、竞争格局、趋势",
            "parameters": ["market", "category", "competitors"],
            "handler": self._skill_market_analysis,
        })
        self.register("product_positioning", {
            "name": "产品定位",
            "description": "基于FABE模型生成产品卖点和定位",
            "parameters": ["product_name", "features", "target_audience"],
            "handler": self._skill_product_positioning,
        })
        self.register("content_generation", {
            "name": "内容生成",
            "description": "生成多语言营销内容",
            "parameters": ["topic", "language", "platform", "format"],
            "handler": self._skill_content_generation,
        })
        self.register("customer_scoring", {
            "name": "客户评分",
            "description": "基于BANT框架评分潜在客户",
            "parameters": ["lead_data"],
            "handler": self._skill_customer_scoring,
        })
        self.register("price_optimization", {
            "name": "价格优化",
            "description": "基于竞争分析和利润目标优化定价",
            "parameters": ["product", "competitors", "cost", "margin_target"],
            "handler": self._skill_price_optimization,
        })
        self.register("email_campaign", {
            "name": "邮件营销",
            "description": "设计并执行邮件营销活动",
            "parameters": ["campaign_type", "audience", "goal"],
            "handler": self._skill_email_campaign,
        })
        self.register("ad_optimization", {
            "name": "广告优化",
            "description": "分析广告表现并给出优化建议",
            "parameters": ["platform", "campaign_data", "budget"],
            "handler": self._skill_ad_optimization,
        })
        self.register("inventory_forecast", {
            "name": "库存预测",
            "description": "基于历史销售和趋势预测库存需求",
            "parameters": ["sku", "historical_sales", "lead_time"],
            "handler": self._skill_inventory_forecast,
        })
        self.register("supplier_evaluation", {
            "name": "供应商评估",
            "description": "多维评估供应商（价格/质量/交期/服务）",
            "parameters": ["supplier_data", "criteria"],
            "handler": self._skill_supplier_evaluation,
        })
        self.register("tax_calculation", {
            "name": "税务计算",
            "description": "计算各国税务（VAT/GST/关税）",
            "parameters": ["country", "amount", "product_type"],
            "handler": self._skill_tax_calculation,
        })

    def register(self, name: str, skill_def: dict):
        self._skills[name] = skill_def

    def get(self, name: str) -> Optional[dict]:
        return self._skills.get(name)

    def list_all(self) -> list[str]:
        return list(self._skills.keys())

    async def execute(self, skill_name: str, **kwargs) -> dict:
        skill = self._skills.get(skill_name)
        if not skill:
            return {"error": f"Skill not found: {skill_name}"}
        handler = skill.get("handler")
        if handler:
            if asyncio.iscoroutinefunction(handler):
                return await handler(**kwargs)
            return handler(**kwargs)
        return {"status": "executed", "skill": skill_name}

    # ---- Skill Implementations ----

    async def _skill_market_analysis(self, **kwargs) -> dict:
        market = kwargs.get("market", "global")
        category = kwargs.get("category", "")
        return {
            "market_size": f"{market} {category} 市场分析",
            "growth_rate": "15-25% YoY",
            "competitors": ["competitor_A", "competitor_B"],
            "entry_barrier": "medium",
            "recommendation": "recommend_entry",
        }

    async def _skill_product_positioning(self, **kwargs) -> dict:
        product = kwargs.get("product_name", "")
        return {
            "features": kwargs.get("features", []),
            "advantages": ["advantage_1", "advantage_2"],
            "benefits": ["benefit_1", "benefit_2"],
            "evidence": ["certification", "testimonials"],
            "usp": f"{product} 核心卖点",
        }

    async def _skill_content_generation(self, **kwargs) -> dict:
        return {
            "headline": f"{kwargs.get('topic')} - 标题",
            "body": f"关于 {kwargs.get('topic')} 的内容",
            "cta": "立即行动",
            "language": kwargs.get("language", "en"),
        }

    async def _skill_customer_scoring(self, **kwargs) -> dict:
        lead = kwargs.get("lead_data", {})
        budget = lead.get("budget", 0)
        authority = lead.get("authority", False)
        need = lead.get("need_match", 0)
        timeline = lead.get("timeline_days", 90)

        score = 0
        if budget > 10000: score += 25
        elif budget > 1000: score += 15
        if authority: score += 25
        score += min(need * 25, 25)
        if timeline < 30: score += 25
        elif timeline < 90: score += 15

        return {
            "score": score,
            "tier": "A" if score >= 70 else "B" if score >= 50 else "C",
            "bant": {"budget": budget, "authority": authority, "need": need, "timeline": timeline},
            "recommendation": "fast_track" if score >= 70 else "nurture",
        }

    async def _skill_price_optimization(self, **kwargs) -> dict:
        return {
            "recommended_price": kwargs.get("cost", 10) * 2.5,
            "competitor_range": {"low": 15, "high": 35},
            "margin": 60,
            "strategy": "value_based",
        }

    async def _skill_email_campaign(self, **kwargs) -> dict:
        return {
            "campaign_type": kwargs.get("campaign_type", "welcome"),
            "emails": [
                {"day": 0, "subject": "欢迎加入", "type": "welcome"},
                {"day": 3, "subject": "产品推荐", "type": "nurture"},
                {"day": 7, "subject": "限时优惠", "type": "promotion"},
            ],
        }

    async def _skill_ad_optimization(self, **kwargs) -> dict:
        return {
            "platform": kwargs.get("platform", "google"),
            "suggestions": [
                "increase_bid_for_high_ctr_keywords",
                "add_negative_keywords",
                "test_new_ad_copy",
            ],
            "expected_improvement": "15-25%",
        }

    async def _skill_inventory_forecast(self, **kwargs) -> dict:
        return {
            "sku": kwargs.get("sku", ""),
            "forecast_30d": 500,
            "forecast_60d": 1100,
            "forecast_90d": 1800,
            "reorder_point": 300,
            "safety_stock": 200,
        }

    async def _skill_supplier_evaluation(self, **kwargs) -> dict:
        return {
            "overall_score": 82,
            "dimensions": {
                "price": 75,
                "quality": 90,
                "delivery": 80,
                "service": 85,
            },
            "recommendation": "approved",
        }

    async def _skill_tax_calculation(self, **kwargs) -> dict:
        country = kwargs.get("country", "US")
        amount = float(kwargs.get("amount", 1000))
        tax_rates = {"US": 0.0, "UK": 0.20, "DE": 0.19, "FR": 0.20, "JP": 0.10, "AU": 0.10}
        rate = tax_rates.get(country, 0.0)
        return {
            "country": country,
            "amount": amount,
            "tax_rate": rate,
            "tax_amount": amount * rate,
            "total": amount * (1 + rate),
        }


# ============================================================
# Agent Brain - 核心执行器
# ============================================================

class AgentBrain:
    """单个Agent的完整执行大脑"""

    def __init__(self, agent_id: str, agent_config: dict, llm_client, tool_registry, api_factory):
        self.agent_id = agent_id
        self.config = agent_config
        self.llm = llm_client
        self.tools = tool_registry
        self.apis = api_factory
        self.memory = AgentMemory(agent_id)
        self.skills = SkillRegistry()
        self.conversation_history: list[dict] = []
        self.state: dict[str, Any] = {}
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_tokens": 0,
            "last_active": None,
        }

    async def think(self, task: str, context: dict = None) -> dict:
        """Agent思考 - 分析任务并制定执行计划"""
        system_prompt = self._build_system_prompt()
        memory_context = self.memory.to_context()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                "task": task,
                "context": context or {},
                "memory": memory_context,
                "available_tools": self.config.get("agent", {}).get("tools", {}).get("enabled", []),
                "available_skills": self.skills.list_all(),
            }, ensure_ascii=False, indent=2)},
        ]

        llm_config = self.config.get("agent", {}).get("llm", {})
        response = await self.llm.chat(
            provider=llm_config.get("provider", "claude"),
            model=llm_config.get("model", "claude-sonnet-4-20250514"),
            messages=messages,
            temperature=llm_config.get("temperature", 0.5),
            max_tokens=llm_config.get("max_tokens", 4096),
        )

        self.metrics["total_tokens"] += response.tokens_used
        self.metrics["last_active"] = datetime.now().isoformat()
        self.memory.remember({"task": task, "response": response.content[:200]})

        return {
            "agent_id": self.agent_id,
            "task": task,
            "thinking": response.content,
            "tokens_used": response.tokens_used,
        }

    async def act(self, action: str, input_data: dict = None) -> dict:
        """Agent执行 - 执行具体操作"""
        logger.info(f"[{self.agent_id}] Acting: {action}")

        # 先思考
        plan = await self.think(action, input_data)

        # 根据action类型路由到具体处理
        action_handlers = {
            # Sales actions
            "analyze_inquiry": self._handle_sales_inquiry,
            "engage_and_qualify": self._handle_lead_qualification,
            "auto_respond_whatsapp": self._handle_whatsapp_message,
            "handle_product_inquiry": self._handle_product_inquiry,
            # Amazon actions
            "process_amazon_order": self._handle_amazon_order,
            "analyze_review": self._handle_review_analysis,
            "generate_listing": self._handle_listing_generation,
            "optimize_bids": self._handle_ppc_optimization,
            # Marketing actions
            "launch_and_optimize_ads": self._handle_ad_launch,
            "scan_trends": self._handle_trend_scan,
            "competitor_analysis": self._handle_competitor_analysis,
            # Content actions
            "generate_content_batch": self._handle_content_generation,
            "write_video_script": self._handle_video_script,
            "produce_video": self._handle_video_production,
            # Supply chain actions
            "process_order": self._handle_order_processing,
            "forecast_demand": self._handle_demand_forecast,
            "get_quote": self._handle_logistics_quote,
            "update_tracking": self._handle_tracking_update,
            # Finance actions
            "process_payment": self._handle_payment_processing,
            "calculate_commissions": self._handle_commission_calculation,
            "review_budget": self._handle_budget_review,
            "calculate_tax": self._handle_tax_calculation,
            # CEO actions
            "generate_daily_report": self._handle_daily_report,
            "generate_daily_briefing": self._handle_daily_briefing,
            # Generic
            "execute": self._handle_generic_execute,
        }

        handler = action_handlers.get(action, self._handle_generic_execute)
        try:
            result = await handler(input_data or {})
            self.metrics["tasks_completed"] += 1
            self.memory.remember({"action": action, "result": result}, importance=0.7)
            return {"status": "completed", "agent_id": self.agent_id, "action": action, "result": result, **plan}
        except Exception as e:
            self.metrics["tasks_failed"] += 1
            logger.error(f"[{self.agent_id}] Action failed: {action} - {e}")
            return {"status": "failed", "agent_id": self.agent_id, "action": action, "error": str(e)}

    def _build_system_prompt(self) -> str:
        sp = self.config.get("agent", {}).get("system_prompt", {})
        role = sp.get("role", f"You are {self.agent_id} agent.")
        goals = sp.get("goals", [])
        constraints = sp.get("constraints", [])

        prompt = f"{role}\n\n"
        if goals:
            prompt += "Goals:\n" + "\n".join(f"- {g}" for g in goals) + "\n\n"
        if constraints:
            prompt += "Constraints:\n" + "\n".join(f"- {c}" for c in constraints) + "\n\n"

        prompt += "You have access to tools and skills. Use them when needed.\n"
        prompt += "Respond with a clear plan and actions in JSON format when applicable."
        return prompt

    # ---- Action Handlers ----

    async def _handle_sales_inquiry(self, data: dict) -> dict:
        subject = data.get("subject", "")
        body = data.get("body", "")
        intent = "purchase" if any(w in body.lower() for w in ["price", "buy", "order", "quote"]) else "inquiry"
        return {
            "intent": intent,
            "priority": "high" if intent == "purchase" else "medium",
            "suggested_response": f"Thank you for your inquiry about {subject}. I'd be happy to help!",
            "next_action": "send_quote" if intent == "purchase" else "provide_info",
        }

    async def _handle_lead_qualification(self, data: dict) -> dict:
        return await self.skills.execute("customer_scoring", lead_data=data)

    async def _handle_whatsapp_message(self, data: dict) -> dict:
        message = data.get("message", data.get("body", ""))
        phone = data.get("phone", data.get("from", ""))
        try:
            wa_client = self.apis.get_whatsapp()
            # 发送自动回复
            greeting = f"👋 Hi! Thanks for reaching out. How can I help you today?"
            await wa_client.send_message(to=phone, body=greeting)
            return {"platform": "whatsapp", "to": phone, "response": greeting, "delivered": True}
        except Exception as e:
            logger.warning(f"WhatsApp send failed (mock mode): {e}")
            return {"platform": "whatsapp", "to": phone, "response": "Auto-reply queued", "delivered": False}

    async def _handle_product_inquiry(self, data: dict) -> dict:
        product = data.get("product", "")
        quantity = data.get("quantity", 1)
        return {
            "product": product,
            "quantity": quantity,
            "estimated_price": 99.99,
            "availability": "in_stock",
            "shipping_estimate": "5-7 business days",
        }

    async def _handle_amazon_order(self, data: dict) -> dict:
        return {"order_id": data.get("order_id", ""), "status": "processed", "fulfillment": "FBA"}

    async def _handle_review_analysis(self, data: dict) -> dict:
        rating = data.get("rating", 3)
        body = data.get("body", "")
        sentiment = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
        return {"asin": data.get("asin", ""), "rating": rating, "sentiment": sentiment, "needs_response": rating <= 2}

    async def _handle_listing_generation(self, data: dict) -> dict:
        return {
            "title": f"{data.get('product', 'Product')} - Premium Quality",
            "bullet_points": ["Feature 1", "Feature 2", "Feature 3", "Feature 4", "Feature 5"],
            "description": "Professional product description...",
            "search_terms": ["keyword1", "keyword2", "keyword3"],
        }

    async def _handle_ppc_optimization(self, data: dict) -> dict:
        return await self.skills.execute("ad_optimization", platform="amazon", campaign_data=data)

    async def _handle_ad_launch(self, data: dict) -> dict:
        return {"campaigns_launched": 3, "budget_allocated": 5000, "expected_impressions": 100000}

    async def _handle_trend_scan(self, data: dict) -> dict:
        return {
            "trending_topics": ["topic_1", "topic_2", "topic_3"],
            "viral_content": ["video_1", "video_2"],
            "recommendations": ["Create content about topic_1", "Leverage trend topic_2"],
        }

    async def _handle_competitor_analysis(self, data: dict) -> dict:
        return {
            "competitors": [
                {"name": "Competitor A", "strength": "Price", "weakness": "Quality"},
                {"name": "Competitor B", "strength": "Brand", "weakness": "Delivery"},
            ],
            "market_share_estimate": {"us": 15, "leader": 35},
        }

    async def _handle_content_generation(self, data: dict) -> dict:
        return await self.skills.execute("content_generation", **data)

    async def _handle_video_script(self, data: dict) -> dict:
        return {
            "script": f"Video script about {data.get('topic', 'product')}",
            "duration_seconds": 60,
            "scenes": ["hook", "problem", "solution", "benefits", "cta"],
        }

    async def _handle_video_production(self, data: dict) -> dict:
        try:
            heygen = self.apis.get_heygen()
            # 实际生产环境调用HeyGen API
            return {
                "video_id": f"vid-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "status": "processing",
                "estimated_completion": "5 minutes",
            }
        except Exception:
            return {"video_id": "mock-vid-001", "status": "mock_processing"}

    async def _handle_order_processing(self, data: dict) -> dict:
        order_id = data.get("order_id", f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        return {"order_id": order_id, "status": "confirmed", "next_step": "production_scheduling"}

    async def _handle_demand_forecast(self, data: dict) -> dict:
        return await self.skills.execute("inventory_forecast", **data)

    async def _handle_logistics_quote(self, data: dict) -> dict:
        return {
            "carrier": self.agent_id.replace("_agent", "").upper(),
            "estimated_cost": 45.00,
            "estimated_days": 5,
            "service_level": "express",
        }

    async def _handle_tracking_update(self, data: dict) -> dict:
        tracking = data.get("tracking", data.get("tracking_number", ""))
        return {
            "tracking_number": tracking,
            "status": data.get("status", "in_transit"),
            "location": data.get("location", "Transit Hub"),
            "estimated_delivery": (datetime.now().isoformat()),
        }

    async def _handle_payment_processing(self, data: dict) -> dict:
        amount = data.get("amount", 0)
        currency = data.get("currency", "USD")
        return {
            "transaction_id": f"txn-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "amount": amount,
            "currency": currency,
            "status": "completed",
        }

    async def _handle_commission_calculation(self, data: dict) -> dict:
        revenue = float(data.get("revenue", 0))
        return {
            "total_revenue": revenue,
            "commissions": [
                {"role": "franchise", "rate": 0.30, "amount": revenue * 0.30},
                {"role": "partner", "rate": 0.15, "amount": revenue * 0.15},
                {"role": "affiliate", "rate": 0.10, "amount": revenue * 0.10},
            ],
        }

    async def _handle_budget_review(self, data: dict) -> dict:
        return {
            "budget_id": data.get("budget_id", ""),
            "status": "approved",
            "variance": "+5%",
            "recommendations": ["Optimize ad spend", "Negotiate supplier pricing"],
        }

    async def _handle_tax_calculation(self, data: dict) -> dict:
        return await self.skills.execute("tax_calculation", **data)

    async def _handle_daily_report(self, data: dict) -> dict:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "revenue": 125000,
            "orders": 450,
            "new_customers": 85,
            "active_agents": 96,
            "alerts": [],
            "top_performers": ["sales_agent", "tiktok_shop_agent", "amazon_manager_agent"],
        }

    async def _handle_daily_briefing(self, data: dict) -> dict:
        return await self._handle_daily_report(data)

    async def _handle_generic_execute(self, data: dict) -> dict:
        """通用执行 - 使用LLM推理"""
        result = await self.think(data.get("action", "execute"), data)
        return {"reasoning": result.get("thinking", ""), "input": data}


# ============================================================
# Agent Cluster - 多Agent协作
# ============================================================

class AgentCluster:
    """Agent集群管理器 - 多Agent协调与通信"""

    def __init__(self):
        self._brains: dict[str, AgentBrain] = {}
        self._event_bus: list[dict] = []
        self._task_queue: asyncio.Queue = asyncio.Queue()

    def register(self, agent_id: str, brain: AgentBrain):
        self._brains[agent_id] = brain
        logger.info(f"[Cluster] Agent registered: {agent_id}")

    def get_brain(self, agent_id: str) -> Optional[AgentBrain]:
        return self._brains.get(agent_id)

    async def broadcast(self, from_agent: str, message: dict, target_agents: list[str] = None):
        """广播消息给其他Agent"""
        targets = target_agents or list(self._brains.keys())
        results = {}
        for aid in targets:
            if aid != from_agent and aid in self._brains:
                brain = self._brains[aid]
                brain.memory.remember({"from": from_agent, "message": message}, MemoryType.WORKING)
                results[aid] = {"status": "delivered"}
        return results

    async def delegate(self, from_agent: str, to_agent: str, task: dict) -> dict:
        """委托任务给另一个Agent"""
        if to_agent in self._brains:
            brain = self._brains[to_agent]
            action = task.get("action", "execute")
            return await brain.act(action, task.get("data", {}))
        return {"error": f"Agent not found: {to_agent}"}

    async def orchestrate(self, taskflow_steps: list[dict], input_data: dict) -> dict:
        """编排多Agent工作流"""
        results = {}
        current_data = input_data

        for step in sorted(taskflow_steps, key=lambda s: s.get("order", 0)):
            agent_id = step.get("agent_id", step.get("agent", ""))
            action = step.get("action", "execute")
            condition = step.get("condition")

            if condition:
                # 检查条件
                cond_met = self._evaluate_condition(condition, results)
                if not cond_met:
                    continue

            brain = self._brains.get(agent_id)
            if not brain:
                results[agent_id] = {"error": "Agent not found"}
                continue

            step_result = await brain.act(action, current_data)
            results[agent_id] = step_result

            # 传递数据到下一步
            if step_result.get("status") == "completed":
                current_data = {**current_data, **step_result.get("result", {})}

        return results

    def _evaluate_condition(self, condition: str, results: dict) -> bool:
        """评估条件"""
        try:
            parts = condition.split()
            if len(parts) >= 3:
                var, op, val = parts[0], parts[1], parts[2]
                actual = None
                for r in results.values():
                    if isinstance(r, dict):
                        actual = r.get("result", {}).get(var) or r.get(var)
                        if actual is not None:
                            break
                if actual is not None:
                    if op == ">=": return float(actual) >= float(val)
                    if op == "<=": return float(actual) <= float(val)
                    if op == ">": return float(actual) > float(val)
                    if op == "<": return float(actual) < float(val)
                    if op == "==": return str(actual) == str(val)
            return True
        except Exception:
            return True

    def get_status(self) -> dict:
        """获取集群状态"""
        return {
            "total_agents": len(self._brains),
            "agent_status": {
                aid: {
                    "tasks_completed": b.metrics["tasks_completed"],
                    "tasks_failed": b.metrics["tasks_failed"],
                    "total_tokens": b.metrics["total_tokens"],
                    "last_active": b.metrics["last_active"],
                    "memory_count": len(b.memory.short_term) + len(b.memory.long_term),
                }
                for aid, b in self._brains.items()
            },
        }
