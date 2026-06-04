"""
Agent Runtime 执行引擎
真正的 LLM 调用、工具执行、上下文管理
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

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


# ============================================================
# LLM Client Abstraction
# ============================================================

class LLMProvider(Enum):
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

        formatted_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        if provider == "claude":
            return await self._call_claude(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider == "openai":
            return await self._call_openai(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider == "gemini":
            return await self._call_gemini(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider == "deepseek":
            return await self._call_deepseek(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        elif provider == "qwen":
            return await self._call_qwen(model, formatted_messages, temperature, max_tokens, tools, api_key, api_base)
        else:
            # 回退到 mock 响应（开发环境）
            return await self._call_mock(provider, model, formatted_messages, temperature, max_tokens)

    async def _call_openai(self, model, messages, temperature, max_tokens, tools, api_key, api_base):
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=api_base)
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

    async def _call_deepseek(self, model, messages, temperature, max_tokens, tools, api_key, api_base):
        return await self._call_openai(model, messages, temperature, max_tokens, tools, api_key, api_base)

    async def _call_qwen(self, model, messages, temperature, max_tokens, tools, api_key, api_base):
        return await self._call_openai(model, messages, temperature, max_tokens, tools, api_key, api_base)

    async def _call_mock(self, provider, model, messages, temperature, max_tokens) -> LLMResponse:
        """开发/测试用 mock 响应"""
        last_user_msg = messages[-1]["content"] if messages else ""
        return LLMResponse(
            content=f"[{provider}/{model}] Agent response to: {last_user_msg[:100]}...",
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

    # ---- 内置工具实现 ----

    async def _tool_web_search(self, query: str, **kwargs) -> dict:
        logger.info(f"[Tool:web_search] {query}")
        return {"results": [{"title": "Search result", "snippet": f"Info about: {query}"}]}

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
        session_id = f"{agent_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        logger.info(f"[AgentExecutor] Executing {agent_id}: {action}")

        # 构建系统提示词
        llm_cfg = agent_config.get("agent", {}).get("llm", {})
        system_prompt = agent_config.get("agent", {}).get("system_prompt", {}).get("role", "")
        enabled_tools = agent_config.get("agent", {}).get("tools", {}).get("enabled", [])

        # 构建消息
        messages = [
            Message(role="system", content=system_prompt),
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
            response = await self.llm.chat(
                provider=llm_cfg.get("provider", "claude"),
                model=llm_cfg.get("model", "claude-3-sonnet"),
                messages=messages,
                temperature=llm_cfg.get("temperature", 0.5),
                max_tokens=llm_cfg.get("max_tokens", 4096),
            )

            # 解析响应中的工具调用（简化处理）
            result = self._parse_agent_response(response.content)

            # 执行工具调用
            if result.get("tool_calls"):
                for tc in result["tool_calls"]:
                    tool_name = tc.get("name")
                    if tool_name in enabled_tools:
                        tool_result = await self.tools.execute(tool_name, **tc.get("arguments", {}))
                        result.setdefault("tool_results", {})[tool_name] = tool_result

            return {
                "agent_id": agent_id,
                "action": action,
                "status": "completed",
                "session_id": session_id,
                "response": response.content,
                "parsed_result": result,
                "tokens_used": response.tokens_used,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"[AgentExecutor] Error executing {agent_id}: {e}")
            return {
                "agent_id": agent_id,
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def _parse_agent_response(self, content: str) -> dict:
        """解析 Agent 响应中的结构化数据"""
        result = {"content": content, "tool_calls": []}

        # 尝试从响应中提取 JSON
        try:
            # 查找 JSON 块
            import re
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

    def load_agent(self, config_path: str) -> dict:
        """加载 Agent 配置"""
        full_path = self.base_path / config_path
        if not full_path.exists():
            raise FileNotFoundError(f"Agent config not found: {full_path}")
        config = _rt_load_toml(str(full_path))
        agent_id = config.get("agent", {}).get("id")
        if agent_id:
            self._agent_configs[agent_id] = config
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

    def get_agent_config(self, agent_id: str) -> Optional[dict]:
        return self._agent_configs.get(agent_id)
