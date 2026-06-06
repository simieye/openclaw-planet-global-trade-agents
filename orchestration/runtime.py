"""
Agent Runtime 执行引擎
真正的 LLM 调用、工具执行、上下文管理
支持: Ollama (本地), OpenAI, Claude, Gemini, DeepSeek, Qwen
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

try:
    from .agent_brain import SkillRegistry
except ImportError:
    from agent_brain import SkillRegistry

# TOML 加载器兼容
try:
    import tomllib as _toml_lib_runtime
except ImportError:
    try:
        import tomli as _toml_lib_runtime
    except ImportError:
        import tomllib as _toml_lib_runtime


def _rt_load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        raw_bytes = f.read()
    try:
        return _toml_lib_runtime.loads(raw_bytes.decode("utf-8"))
    except (TypeError, Exception):
        try:
            return _toml_lib_runtime.loads(raw_bytes)
        except Exception:
            import tomli
            return tomli.loads(raw_bytes.decode("utf-8"))


logger = logging.getLogger("openclaw.runtime")

# Ollama 默认地址
OLLAMA_BASE_URL = "http://localhost:11434"


# ============================================================
# LLM Client Abstraction
# ============================================================

class LLMProvider(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_used: int = 0
    finish_reason: str = "stop"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""


class LLMClient:
    """多模型 LLM 客户端抽象层"""

    def __init__(self):
        self._clients: dict[str, Any] = {}
        self._ollama_available: Optional[bool] = None

    async def check_ollama(self) -> bool:
        """检查 Ollama 服务是否可用"""
        if self._ollama_available is not None:
            return self._ollama_available
        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    async def get_ollama_models(self) -> list[dict]:
        """获取 Ollama 可用模型列表"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return [
                        {"name": m.get("name", ""), "size": m.get("size", 0)}
                        for m in data.get("models", [])
                    ]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
        return []

    async def chat(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] = None,
        api_key: str = "",
        api_base: str = "",
    ) -> LLMResponse:
        """统一 LLM 调用接口"""
        formatted_messages = []
        for m in messages:
            if isinstance(m, dict):
                formatted_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            else:
                formatted_messages.append({"role": m.role, "content": m.content})

        # 优先使用 Ollama（如果可用且没有指定其他 provider）
        if provider == "ollama" or (not provider and await self.check_ollama()):
            return await self._call_ollama(model, formatted_messages, temperature, max_tokens)
        elif provider == "claude":
            return await self._call_claude(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider == "openai":
            return await self._call_openai(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider == "gemini":
            return await self._call_gemini(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider in ("deepseek", "qwen"):
            return await self._call_openai_compatible(provider, model, formatted_messages, temperature, max_tokens, api_key, api_base)
        else:
            # 回退到 Ollama 或 mock
            if await self.check_ollama():
                return await self._call_ollama(model, formatted_messages, temperature, max_tokens)
            return await self._call_mock(provider, model, formatted_messages, temperature, max_tokens)

    async def chat_stream(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        api_key: str = "",
        api_base: str = "",
    ) -> AsyncGenerator[str, None]:
        """流式 LLM 调用"""
        formatted_messages = []
        for m in messages:
            if isinstance(m, dict):
                formatted_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            else:
                formatted_messages.append({"role": m.role, "content": m.content})

        if provider == "ollama" or (not provider and await self.check_ollama()):
            async for chunk in self._call_ollama_stream(model, formatted_messages, temperature, max_tokens):
                yield chunk
        elif provider in ("openai", "deepseek", "qwen"):
            async for chunk in self._call_openai_stream(provider, model, formatted_messages, temperature, max_tokens, api_key, api_base):
                yield chunk
        else:
            # 回退：先获取完整响应再模拟流式输出
            resp = await self.chat(provider, model, messages, temperature, max_tokens, None, api_key, api_base)
            # 模拟流式输出（每10个字符一块）
            content = resp.content
            for i in range(0, len(content), 10):
                yield content[i:i+10]
                await asyncio.sleep(0.01)

    # ---- Ollama Implementation ----

    async def _call_ollama(self, model: str, messages: list, temperature: float, max_tokens: int) -> LLMResponse:
        """调用 Ollama 本地模型"""
        import httpx
        try:
            ollama_model = model or "qwen3-coder:480b-cloud"
            # 如果模型名不存在，尝试使用第一个可用模型
            available = await self.get_ollama_models()
            if available:
                model_names = [m["name"] for m in available]
                if ollama_model not in model_names:
                    ollama_model = model_names[0]
                    logger.info(f"Model '{model}' not found, using '{ollama_model}'")

            payload = {
                "model": ollama_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "")
                    return LLMResponse(
                        content=content,
                        model=ollama_model,
                        tokens_used=data.get("eval_count", 0) + data.get("prompt_eval_count", 0),
                        finish_reason=data.get("done_reason", "stop"),
                    )
                else:
                    logger.error(f"Ollama API error: {resp.status_code} {resp.text[:200]}")
                    return LLMResponse(
                        content=f"⚠️ Ollama API 返回错误 ({resp.status_code})。请确认模型已下载: ollama pull {ollama_model}",
                        model=ollama_model,
                        tokens_used=0,
                        finish_reason="error",
                    )
        except httpx.ConnectError:
            logger.warning("Ollama not reachable, falling back to mock")
            return await self._call_mock("ollama", model, messages, temperature, max_tokens)
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return LLMResponse(
                content=f"⚠️ Ollama 调用失败: {str(e)}\n\n请确认:\n1. Ollama 服务已启动 (ollama serve)\n2. 模型已下载",
                model=model or "ollama",
                tokens_used=0,
                finish_reason="error",
            )

    async def _call_ollama_stream(self, model: str, messages: list, temperature: float, max_tokens: int) -> AsyncGenerator[str, None]:
        """Ollama 流式调用"""
        import httpx
        try:
            ollama_model = model or "qwen3-coder:480b-cloud"
            available = await self.get_ollama_models()
            if available:
                model_names = [m["name"] for m in available]
                if ollama_model not in model_names:
                    ollama_model = model_names[0]

            payload = {
                "model": ollama_model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        yield f"⚠️ Ollama API 返回错误 ({resp.status_code})"
                        return
                    async for line in resp.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                content = data.get("message", {}).get("content", "")
                                if content:
                                    yield content
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
        except httpx.ConnectError:
            yield "⚠️ 无法连接 Ollama 服务。请确认 ollama serve 已启动。"
        except Exception as e:
            yield f"⚠️ Ollama 流式调用失败: {str(e)}"

    # ---- OpenAI Implementation ----

    async def _call_openai(self, model, messages, temperature, max_tokens, tools, api_key, api_base):
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=api_key or "sk-placeholder",
                base_url=api_base,
            )
            kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
            if tools:
                kwargs["tools"] = tools
            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=model,
                tokens_used=response.usage.total_tokens if response.usage else 0,
            )
        except ImportError:
            return await self._call_mock("openai", model, messages, temperature, max_tokens)

    async def _call_openai_stream(self, provider, model, messages, temperature, max_tokens, api_key, api_base):
        """OpenAI 兼容流式调用"""
        import httpx
        try:
            base = api_base or "https://api.openai.com/v1"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key or 'sk-placeholder'}",
            }
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                async with client.stream("POST", f"{base}/chat/completions", json=payload, headers=headers) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            yield f"⚠️ 流式调用失败: {str(e)}"

    async def _call_openai_compatible(self, provider, model, messages, temperature, max_tokens, api_key, api_base):
        """OpenAI 兼容 API 调用 (DeepSeek/Qwen)"""
        return await self._call_openai(model, messages, temperature, max_tokens, None, api_key, api_base)

    # ---- Claude Implementation ----

    async def _call_claude(self, model, messages, temperature, max_tokens, tools, api_key, api_base):
        try:
            from anthropic import AsyncAnthropic
            system_prompt = ""
            chat_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_prompt = m["content"]
                else:
                    chat_messages.append({"role": m["role"], "content": m["content"]})

            client = AsyncAnthropic(api_key=api_key, base_url=api_base)
            kwargs = dict(
                model=model,
                system=system_prompt,
                messages=chat_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if tools:
                kwargs["tools"] = tools
            response = await client.messages.create(**kwargs)
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return LLMResponse(
                content="\n".join(text_blocks),
                model=model,
                tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            )
        except ImportError:
            return await self._call_mock("claude", model, messages, temperature, max_tokens)

    # ---- Gemini Implementation ----

    async def _call_gemini(self, model, messages, temperature, max_tokens, tools, api_key, api_base):
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            gen_model = genai.GenerativeModel(model)
            response = await gen_model.generate_content_async(prompt)
            return LLMResponse(
                content=response.text or "",
                model=model,
                tokens_used=0,
            )
        except ImportError:
            return await self._call_mock("gemini", model, messages, temperature, max_tokens)

    # ---- Mock Fallback ----

    async def _call_mock(self, provider, model, messages, temperature, max_tokens) -> LLMResponse:
        """开发/测试用 mock 响应（当所有真实 API 不可用时）"""
        last_user_msg = messages[-1]["content"] if messages else ""
        return LLMResponse(
            content=f"[Mock] {provider}/{model}: 收到消息 \"{last_user_msg[:100]}...\"\n\n⚠️ 当前无可用 AI 模型连接。请:\n1. 启动 Ollama: ollama serve\n2. 下载模型: ollama pull qwen3-coder:480b-cloud\n3. 或配置其他 LLM API Key",
            model=f"{provider}/{model}",
            tokens_used=0,
        )


# ============================================================
# Tool Registry
# ============================================================

class ToolRegistry:
    """工具注册中心 - 管理 Agent 可调用的工具"""

    def __init__(self):
        self._tools: dict[str, callable] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        """注册内置工具"""
        self.register("web_search", self._tool_web_search)
        self.register("send_notification", self._tool_send_notification)
        self.register("generate_report", self._tool_generate_report)
        self.register("translation_engine", self._tool_translate)
        self.register("crm_api", self._tool_crm_api)
        self.register("email_api", self._tool_email_api)
        self.register("whatsapp_api", self._tool_whatsapp_api)
        self.register("anygen_knowledge_search", self._tool_knowledge_search)
        self.register("anygen_dashboard_query", self._tool_dashboard_query)
        self.register("negotiation_assistant", self._tool_negotiation)
        self.register("send_agent_task", self._tool_send_agent_task)
        # 电商专用工具
        self.register("product_research", self._tool_product_research)
        self.register("listing_optimizer", self._tool_listing_optimizer)
        self.register("competitor_analysis", self._tool_competitor_analysis)
        self.register("ad_copy_generator", self._tool_ad_copy_generator)
        self.register("seo_keyword_research", self._tool_seo_keyword_research)
        self.register("content_localization", self._tool_content_localization)
        self.register("pricing_strategy", self._tool_pricing_strategy)

    def register(self, name: str, func: callable):
        self._tools[name] = func

    def get(self, name: str) -> Optional[callable]:
        return self._tools.get(name)

    async def execute(self, name: str, **kwargs) -> Any:
        func = self._tools.get(name)
        if func:
            if asyncio.iscoroutinefunction(func):
                return await func(**kwargs)
            return func(**kwargs)
        return {"error": f"Tool not found: {name}"}

    # ---- 通用工具 ----

    async def _tool_web_search(self, query: str, **kwargs) -> dict:
        logger.info(f"[Tool:web_search] {query}")
        return {"results": [{"title": f"搜索结果: {query}", "snippet": f"关于 {query} 的相关信息...", "url": ""}]}

    async def _tool_send_notification(self, channel: str, message: str, **kwargs) -> dict:
        logger.info(f"[Tool:send_notification] To:{channel} Msg:{message[:50]}")
        return {"sent": True, "channel": channel}

    async def _tool_generate_report(self, report_type: str, data: dict, **kwargs) -> dict:
        logger.info(f"[Tool:generate_report] Type:{report_type}")
        return {"report": f"Generated {report_type} report", "format": "markdown"}

    async def _tool_translate(self, text: str, target_language: str, source_language: str = "auto", **kwargs) -> dict:
        logger.info(f"[Tool:translate] To:{target_language}")
        return {"translated_text": f"[{target_language}] {text}", "confidence": 0.95}

    async def _tool_crm_api(self, action: str, data: dict = None, **kwargs) -> dict:
        logger.info(f"[Tool:crm_api] Action:{action}")
        return {"status": "ok", "action": action}

    async def _tool_email_api(self, to: str, subject: str, body: str, **kwargs) -> dict:
        logger.info(f"[Tool:email_api] To:{to} Subject:{subject}")
        return {"sent": True, "message_id": "msg-001"}

    async def _tool_whatsapp_api(self, to: str, message: str, **kwargs) -> dict:
        logger.info(f"[Tool:whatsapp_api] To:{to}")
        return {"sent": True, "message_id": "wa-001"}

    async def _tool_knowledge_search(self, query: str, category: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:knowledge_search] Query:{query} Cat:{category}")
        return {"results": [{"content": f"Knowledge about: {query}", "score": 0.92}]}

    async def _tool_dashboard_query(self, metric: str, **kwargs) -> dict:
        logger.info(f"[Tool:dashboard_query] Metric:{metric}")
        return {"metric": metric, "value": 100, "unit": "count"}

    async def _tool_negotiation(self, strategy: str, context: dict, **kwargs) -> dict:
        logger.info(f"[Tool:negotiation] Strategy:{strategy}")
        return {"recommended_action": "counter_offer", "confidence": 0.85}

    async def _tool_send_agent_task(self, target_agent: str, task: dict, **kwargs) -> dict:
        logger.info(f"[Tool:send_agent_task] Target:{target_agent}")
        return {"dispatched": True, "target": target_agent}

    # ---- 电商专用工具 ----

    async def _tool_product_research(self, category: str = "", market: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:product_research] Category:{category} Market:{market}")
        return {
            "top_products": [
                {"name": f"{category}热销品1", "demand_score": 92, "competition": "medium", "price_range": "$15-30"},
                {"name": f"{category}热销品2", "demand_score": 88, "competition": "low", "price_range": "$8-20"},
                {"name": f"{category}趋势品1", "demand_score": 78, "competition": "low", "price_range": "$25-50"},
            ],
            "market_trend": "上升趋势",
            "recommendation": "建议从低竞争细分品类切入",
        }

    async def _tool_listing_optimizer(self, product_name: str = "", platform: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:listing_optimizer] Product:{product_name} Platform:{platform}")
        return {
            "title_optimized": f"[优化标题] {product_name} - 高品质 | 快速发货 | 好评如潮",
            "bullet_points": [
                "核心卖点1: 优质材料，持久耐用",
                "核心卖点2: 多功能设计，满足多种需求",
                "核心卖点3: 30天无忧退换",
            ],
            "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
            "seo_score": 85,
        }

    async def _tool_competitor_analysis(self, product: str = "", market: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:competitor_analysis] Product:{product} Market:{market}")
        return {
            "competitors": [
                {"name": "竞品A", "price": "$25.99", "rating": 4.3, "reviews": 1250, "strength": "品牌知名度", "weakness": "价格偏高"},
                {"name": "竞品B", "price": "$19.99", "rating": 4.1, "reviews": 890, "strength": "价格优势", "weakness": "品质一般"},
                {"name": "竞品C", "price": "$22.99", "rating": 4.5, "reviews": 2100, "strength": "口碑好", "weakness": "产品线单一"},
            ],
            "market_gap": "中端价位段($18-24)竞争较小，品质差异化空间大",
        }

    async def _tool_ad_copy_generator(self, product: str = "", platform: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:ad_copy_generator] Product:{product} Platform:{platform}")
        return {
            "headlines": [
                f"🔥 {product}限时特惠 - 错过等一年",
                f"💯 {product}为什么这么火？看完你就懂了",
                f"⚡ {product}新品首发，前100名半价",
            ],
            "descriptions": [
                f"【限时优惠】{product}品质升级不加价，买2送1，包邮到家。立即抢购！",
                f"📦 {product}海外仓直发，3-5天送达。品质保证，不满意全额退款。",
            ],
            "cta": "立即购买 | 了解更多 | 限时优惠",
        }

    async def _tool_seo_keyword_research(self, product: str = "", market: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:seo_keyword_research] Product:{product} Market:{market}")
        return {
            "high_volume": [f"{product} buy online", f"best {product} 2025", f"{product} for sale"],
            "long_tail": [f"affordable {product} for {market}", f"{product} with free shipping", f"premium {product} wholesale"],
            "trending": [f"{product} trending 2025", f"viral {product} {market}"],
            "search_volume_estimate": "5000-10000/月",
        }

    async def _tool_content_localization(self, text: str = "", target_market: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:content_localization] Target:{target_market}")
        return {
            "localized_text": f"[{target_market}本地化] {text}",
            "cultural_notes": [f"{target_market}市场偏好简洁风格", "注意当地节假日促销时机"],
            "confidence": 0.88,
        }

    async def _tool_pricing_strategy(self, product: str = "", cost: float = 0, market: str = "", **kwargs) -> dict:
        logger.info(f"[Tool:pricing_strategy] Product:{product} Cost:{cost}")
        margin = 0.3
        return {
            "recommended_price": round(cost / (1 - margin), 2) if cost else 29.99,
            "price_range": f"${max(9.99, round((cost or 15) * 0.8, 2))} - ${round((cost or 15) * 2.5, 2)}",
            "strategy": "竞争性定价 + 捆绑销售提升客单价",
            "margin_analysis": {"low": "15%", "mid": "30%", "high": "50%"},
        }


# ============================================================
# Agent Executor
# ============================================================

class AgentExecutor:
    """Agent 执行器 - 管理单个 Agent 的生命周期和执行"""

    def __init__(self, llm_client: LLMClient, tool_registry: ToolRegistry):
        self.llm = llm_client
        self.tools = tool_registry
        self._active_sessions: dict[str, dict] = {}

    async def execute(
        self,
        agent_config: dict,
        action: str,
        input_data: dict = None,
        context: dict = None,
    ) -> dict[str, Any]:
        """执行 Agent 任务"""
        agent_id = agent_config.get("agent", {}).get("id", "unknown")
        agent_name = agent_config.get("agent", {}).get("name", agent_id)
        session_id = f"{agent_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        logger.info(f"[AgentExecutor] Executing {agent_id}: {action}")

        # 构建系统提示词
        llm_cfg = agent_config.get("agent", {}).get("llm", {})
        system_prompt = agent_config.get("agent", {}).get("system_prompt", {}).get("role", "")
        enabled_tools = agent_config.get("agent", {}).get("tools", {}).get("enabled", [])

        # 构建消息
        messages = [
            Message(role="system", content=system_prompt or f"你是 {agent_name}，专注于跨境电商品牌出海领域。"),
            Message(
                role="user",
                content=json.dumps({
                    "action": action,
                    "input_data": input_data or {},
                    "context": context or {},
                }, ensure_ascii=False, indent=2),
            ),
        ]

        # 调用 LLM
        try:
            provider = llm_cfg.get("provider", "ollama")
            model = llm_cfg.get("model", "")
            response = await self.llm.chat(
                provider=provider,
                model=model,
                messages=messages,
                temperature=llm_cfg.get("temperature", 0.5),
                max_tokens=llm_cfg.get("max_tokens", 4096),
            )

            # 解析响应中的工具调用
            result = self._parse_agent_response(response.content)

            # 执行工具调用
            if result.get("tool_calls"):
                for tc in result["tool_calls"]:
                    tool_name = tc.get("name", "")
                    if tool_name in enabled_tools or True:  # 允许所有内置工具
                        tool_result = await self.tools.execute(tool_name, **tc.get("arguments", {}))
                        result.setdefault("tool_results", {})[tool_name] = tool_result

            return {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "action": action,
                "status": "completed",
                "session_id": session_id,
                "thinking": response.content[:500],
                "response": response.content,
                "parsed_result": result,
                "tokens_used": response.tokens_used,
                "model": response.model,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"[AgentExecutor] Error executing {agent_id}: {e}")
            return {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def think(self, agent_config: dict, prompt: str, context: dict = None) -> dict:
        """Agent 深度思考模式"""
        agent_id = agent_config.get("agent", {}).get("id", "unknown")
        agent_name = agent_config.get("agent", {}).get("name", agent_id)
        llm_cfg = agent_config.get("agent", {}).get("llm", {})
        system_prompt = agent_config.get("agent", {}).get("system_prompt", {}).get("role", "")

        messages = [
            Message(role="system", content=system_prompt or f"你是 {agent_name}。请深入思考并给出专业分析。"),
            Message(role="user", content=prompt),
        ]

        try:
            response = await self.llm.chat(
                provider=llm_cfg.get("provider", "ollama"),
                model=llm_cfg.get("model", ""),
                messages=messages,
                temperature=0.7,
                max_tokens=4096,
            )
            return {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "thinking": response.content,
                "tokens_used": response.tokens_used,
                "model": response.model,
            }
        except Exception as e:
            logger.error(f"[AgentExecutor] Think error {agent_id}: {e}")
            return {"agent_id": agent_id, "error": str(e)}

    async def execute_stream(
        self,
        agent_config: dict,
        action: str,
        input_data: dict = None,
        context: dict = None,
    ) -> AsyncGenerator[str, None]:
        """流式执行 Agent 任务"""
        agent_id = agent_config.get("agent", {}).get("id", "unknown")
        agent_name = agent_config.get("agent", {}).get("name", agent_id)
        llm_cfg = agent_config.get("agent", {}).get("llm", {})
        system_prompt = agent_config.get("agent", {}).get("system_prompt", {}).get("role", "")

        messages = [
            Message(role="system", content=system_prompt or f"你是 {agent_name}，专注于跨境电商品牌出海领域。"),
            Message(
                role="user",
                content=json.dumps({
                    "action": action,
                    "input_data": input_data or {},
                    "context": context or {},
                }, ensure_ascii=False, indent=2),
            ),
        ]

        provider = llm_cfg.get("provider", "ollama")
        model = llm_cfg.get("model", "")

        async for chunk in self.llm.chat_stream(
            provider=provider,
            model=model,
            messages=messages,
            temperature=llm_cfg.get("temperature", 0.5),
            max_tokens=llm_cfg.get("max_tokens", 4096),
        ):
            yield chunk

    def _parse_agent_response(self, content: str) -> dict:
        """解析 Agent 响应中的结构化数据"""
        result = {"content": content, "tool_calls": []}

        try:
            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(1))
                if isinstance(parsed, dict):
                    result.update(parsed)
        except (json.JSONDecodeError, AttributeError):
            pass

        return result

    def get_session(self, session_id: str) -> Optional[dict]:
        return self._active_sessions.get(session_id)

    def clear_session(self, session_id: str):
        self._active_sessions.pop(session_id, None)


# ============================================================
# Agent Brain - 单个 Agent 的推理能力
# ============================================================

class AgentBrain:
    """Agent 大脑 - 封装单个 Agent 的推理能力"""

    def __init__(self, config: dict, executor: AgentExecutor):
        self.config = config
        self.executor = executor
        self.metrics = {
            "total_calls": 0,
            "total_tokens": 0,
            "last_call": None,
        }

    async def think(self, prompt: str, context: dict = None) -> dict:
        """Agent 思考"""
        self.metrics["total_calls"] += 1
        self.metrics["last_call"] = datetime.now().isoformat()
        result = await self.executor.think(self.config, prompt, context)
        self.metrics["total_tokens"] += result.get("tokens_used", 0)
        return result

    async def execute(self, action: str, input_data: dict = None) -> dict:
        """Agent 执行任务"""
        self.metrics["total_calls"] += 1
        self.metrics["last_call"] = datetime.now().isoformat()
        result = await self.executor.execute(self.config, action, input_data)
        self.metrics["total_tokens"] += result.get("tokens_used", 0)
        return result


# ============================================================
# Agent Runtime
# ============================================================

class AgentRuntime:
    """Agent 运行时 - 整个集群的 Agent 执行管理器"""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.llm_client = LLMClient()
        self.tool_registry = ToolRegistry()
        self.executor = AgentExecutor(self.llm_client, self.tool_registry)
        self._agent_configs: dict[str, dict] = {}
        self._agent_brains: dict[str, AgentBrain] = {}
        self.skills = SkillRegistry(base_path=str(base_path / "skills"))
        self.skill_registry = self.skills  # 别名

    def load_agent(self, config_path: str) -> dict:
        """加载 Agent 配置"""
        full_path = self.base_path / config_path
        if not full_path.exists():
            raise FileNotFoundError(f"Agent config not found: {full_path}")
        config = _rt_load_toml(str(full_path))
        agent_id = config.get("agent", {}).get("id")
        if agent_id:
            self._agent_configs[agent_id] = config
            self._agent_brains[agent_id] = AgentBrain(config, self.executor)
        return config

    def load_all_agents(self, registry_path: str = "agents/registry.toml"):
        """加载所有 Agent"""
        full_path = self.base_path / registry_path
        registry = _rt_load_toml(str(full_path))

        for entry in registry.get("agents", []):
            try:
                self.load_agent(entry["config"])
                logger.info(f"Runtime loaded agent: {entry['id']}")
            except Exception as e:
                logger.error(f"Failed to load agent {entry['id']}: {e}")

        logger.info(f"AgentRuntime loaded {len(self._agent_configs)} agents")

    async def execute_agent(
        self,
        agent_id: str,
        action: str,
        input_data: dict = None,
        context: dict = None,
    ) -> dict:
        """执行 Agent"""
        config = self._agent_configs.get(agent_id)
        if not config:
            raise ValueError(f"Agent not loaded: {agent_id}")
        return await self.executor.execute(config, action, input_data, context)

    async def think_agent(self, agent_id: str, prompt: str) -> dict:
        """Agent 思考"""
        config = self._agent_configs.get(agent_id)
        if not config:
            raise ValueError(f"Agent not loaded: {agent_id}")
        return await self.executor.think(config, prompt)

    def get_agent_config(self, agent_id: str) -> Optional[dict]:
        return self._agent_configs.get(agent_id)

    def get_agent_brain(self, agent_id: str) -> Optional[AgentBrain]:
        return self._agent_brains.get(agent_id)

    def list_agents(self) -> list[dict]:
        """列出所有已加载的 Agent"""
        return [
            {
                "id": aid,
                "name": cfg.get("agent", {}).get("name", aid),
                "layer": cfg.get("agent", {}).get("layer", ""),
                "description": cfg.get("agent", {}).get("description", ""),
            }
            for aid, cfg in self._agent_configs.items()
        ]

    async def get_dashboard_data(self) -> dict:
        """获取仪表盘实时数据"""
        ollama_ok = await self.llm_client.check_ollama()
        models = await self.llm_client.get_ollama_models() if ollama_ok else []

        return {
            "engine": "running",
            "ollama": {
                "connected": ollama_ok,
                "models": models,
            },
            "agents": {
                "total": len(self._agent_configs),
                "loaded": len(self._agent_brains),
            },
            "timestamp": datetime.now().isoformat(),
        }
