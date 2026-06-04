"""
TaskFlow Engine v2 - 完整的25条工作流执行引擎
条件判断 + 步骤编排 + 错误重试 + 回调通知 + AgentBrain集成
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Callable

logger = logging.getLogger("openclaw.taskflow_v2")


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class FlowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class StepResult:
    order: int
    agent_id: str
    action: str
    status: StepStatus
    result: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FlowExecution:
    flow_id: str
    status: FlowStatus = FlowStatus.PENDING
    steps: list[StepResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_duration_ms: float = 0
    retry_count: int = 0
    max_retries: int = 3


class TaskFlowEngineV2:
    """增强版TaskFlow执行引擎"""

    def __init__(self, runtime=None, webhook_handler=None):
        self.runtime = runtime
        self.webhook_handler = webhook_handler
        self._flows: dict[str, FlowExecution] = {}
        self._flow_definitions: dict[str, dict] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._load_flow_definitions()

    def _load_flow_definitions(self):
        """加载25条TaskFlow定义"""
        self._flow_definitions = {
            "customer_acquisition": {
                "name": "客户成交流水线",
                "steps": [
                    {"order": 1, "agent": "lead_agent", "action": "enrich_and_score_lead"},
                    {"order": 2, "agent": "sdr_agent", "action": "create_outreach_sequence", "condition": "lead_score >= 70"},
                    {"order": 3, "agent": "sales_agent", "action": "engage_and_qualify", "condition": "lead_responded == true"},
                    {"order": 4, "agent": "proposal_agent", "action": "generate_proposal"},
                    {"order": 5, "agent": "quotation_agent", "action": "generate_quotation", "condition": "proposal_accepted == true"},
                    {"order": 6, "agent": "contract_agent", "action": "generate_contract", "condition": "quotation_accepted == true"},
                    {"order": 7, "agent": "payment_agent", "action": "process_payment", "condition": "contract_signed == true"},
                    {"order": 8, "agent": "customer_success_agent", "action": "start_onboarding", "condition": "payment_confirmed == true"},
                ],
            },
            "ecommerce_operations": {
                "name": "电商运营流水线",
                "steps": [
                    {"order": 1, "agent": "trend_agent", "action": "scan_trends"},
                    {"order": 2, "agent": "content_agent", "action": "generate_content_batch"},
                    {"order": 3, "agent": "video_agent", "action": "produce_videos"},
                    {"order": 4, "agent": "ads_agent", "action": "launch_and_optimize_ads"},
                    {"order": 5, "agent": "crm_agent", "action": "sync_and_analyze_customers"},
                    {"order": 6, "agent": "retention_agent", "action": "run_retention_campaign"},
                ],
            },
            "factory_production": {
                "name": "工厂生产流水线",
                "steps": [
                    {"order": 1, "agent": "order_agent", "action": "process_order"},
                    {"order": 2, "agent": "production_agent", "action": "schedule_production", "condition": "inventory_insufficient == true"},
                    {"order": 3, "agent": "procurement_agent", "action": "procure_materials"},
                    {"order": 4, "agent": "quality_agent", "action": "inspect_batch", "condition": "production_completed == true"},
                    {"order": 5, "agent": "logistics_agent", "action": "ship_order", "condition": "quality_passed == true"},
                    {"order": 6, "agent": "order_agent", "action": "update_order_status"},
                ],
            },
            "market_research": {
                "name": "市场调研流水线",
                "steps": [
                    {"order": 1, "agent": "market_agent", "action": "full_market_scan"},
                    {"order": 2, "agent": "product_agent", "action": "optimize_product_positioning"},
                    {"order": 3, "agent": "content_agent", "action": "update_brand_language"},
                ],
            },
            "financial_management": {
                "name": "财务管理流水线",
                "steps": [
                    {"order": 1, "agent": "payment_agent", "action": "reconcile_payments"},
                    {"order": 2, "agent": "accountant_agent", "action": "book_journal_entries"},
                    {"order": 3, "agent": "invoice_agent", "action": "process_invoices"},
                    {"order": 4, "agent": "finance_agent", "action": "generate_financial_report"},
                ],
            },
            "brand_globalization": {
                "name": "品牌出海全流程",
                "steps": [
                    {"order": 1, "agent": "market_agent", "action": "analyze_target_market"},
                    {"order": 2, "agent": "product_agent", "action": "localize_product"},
                    {"order": 3, "agent": "content_agent", "action": "build_content_matrix"},
                    {"order": 4, "agent": "video_agent", "action": "produce_campaign_videos"},
                    {"order": 5, "agent": "ads_agent", "action": "launch_multi_channel_ads"},
                    {"order": 6, "agent": "tiktok_shop_agent", "action": "setup_shop_and_listings"},
                    {"order": 7, "agent": "marketplace_agent", "action": "setup_marketplace_listings"},
                    {"order": 8, "agent": "lead_agent", "action": "mine_target_customers"},
                    {"order": 9, "agent": "sdr_agent", "action": "launch_outreach_campaign"},
                ],
            },
            "franchise_expansion": {
                "name": "全球加盟裂变流水线",
                "steps": [
                    {"order": 1, "agent": "franchise_agent", "action": "discover_franchise_leads"},
                    {"order": 2, "agent": "lead_agent", "action": "enrich_franchise_lead"},
                    {"order": 3, "agent": "sdr_agent", "action": "score_franchise_lead", "condition": "lead_enriched == true"},
                    {"order": 4, "agent": "franchise_agent", "action": "send_franchise_package", "condition": "lead_score >= 70"},
                    {"order": 5, "agent": "heygen_agent", "action": "generate_franchise_video"},
                    {"order": 6, "agent": "sales_agent", "action": "engage_franchise_lead", "condition": "lead_responded == true"},
                    {"order": 7, "agent": "contract_agent", "action": "generate_franchise_contract"},
                    {"order": 8, "agent": "payment_agent", "action": "process_franchise_payment", "condition": "contract_signed == true"},
                    {"order": 9, "agent": "training_agent", "action": "start_franchise_training"},
                    {"order": 10, "agent": "city_node_agent", "action": "activate_city_node"},
                ],
            },
            "opc_project_cocreation": {
                "name": "OPC项目共创流水线",
                "steps": [
                    {"order": 1, "agent": "project_agent", "action": "receive_project"},
                    {"order": 2, "agent": "ecosystem_agent", "action": "evaluate_project"},
                    {"order": 3, "agent": "investment_agent", "action": "investment_review", "condition": "project_score >= 60"},
                    {"order": 4, "agent": "project_agent", "action": "match_resources", "condition": "investment_approved == true"},
                    {"order": 5, "agent": "partner_agent", "action": "assemble_team"},
                    {"order": 6, "agent": "project_agent", "action": "execute_project"},
                    {"order": 7, "agent": "commission_agent", "action": "distribute_revenue", "condition": "project_completed == true"},
                ],
            },
            "global_expansion": {
                "name": "全球扩张流水线",
                "steps": [
                    {"order": 1, "agent": "global_expansion_agent", "action": "analyze_new_market"},
                    {"order": 2, "agent": "market_agent", "action": "deep_market_research"},
                    {"order": 3, "agent": "legal_agent", "action": "compliance_review"},
                    {"order": 4, "agent": "cro_agent", "action": "risk_assessment"},
                    {"order": 5, "agent": "cfo_agent", "action": "financial_feasibility", "condition": "risk_acceptable == true"},
                    {"order": 6, "agent": "global_expansion_agent", "action": "establish_country_center", "condition": "investment_approved == true"},
                    {"order": 7, "agent": "city_node_agent", "action": "activate_city_network"},
                ],
            },
            "ainails_device_operations": {
                "name": "AI NAILS设备运营流水线",
                "steps": [
                    {"order": 1, "agent": "ainails_location_agent", "action": "score_location"},
                    {"order": 2, "agent": "ainails_device_agent", "action": "deploy_device"},
                    {"order": 3, "agent": "logistics_agent", "action": "ship_device"},
                    {"order": 4, "agent": "ainails_device_agent", "action": "activate_device"},
                    {"order": 5, "agent": "store_growth_agent", "action": "start_growth_campaign"},
                    {"order": 6, "agent": "city_node_agent", "action": "update_node_metrics"},
                ],
            },
            "global_settlement": {
                "name": "全球分账流水线",
                "steps": [
                    {"order": 1, "agent": "payment_agent", "action": "collect_daily_revenue"},
                    {"order": 2, "agent": "commission_agent", "action": "calculate_commissions"},
                    {"order": 3, "agent": "partner_agent", "action": "verify_partner_shares"},
                    {"order": 4, "agent": "affiliate_agent", "action": "verify_affiliate_shares"},
                    {"order": 5, "agent": "commission_agent", "action": "execute_settlement"},
                    {"order": 6, "agent": "finance_agent", "action": "generate_settlement_report"},
                ],
            },
            "ceo_dashboard": {
                "name": "CEO经营驾驶舱",
                "steps": [
                    {"order": 1, "agent": "finance_agent", "action": "daily_financial_snapshot"},
                    {"order": 2, "agent": "sales_agent", "action": "daily_sales_snapshot"},
                    {"order": 3, "agent": "crm_agent", "action": "daily_customer_snapshot"},
                    {"order": 4, "agent": "franchise_agent", "action": "daily_franchise_snapshot"},
                    {"order": 5, "agent": "city_node_agent", "action": "daily_node_snapshot"},
                    {"order": 6, "agent": "ecosystem_agent", "action": "daily_ecosystem_snapshot"},
                    {"order": 7, "agent": "cro_agent", "action": "daily_risk_snapshot"},
                    {"order": 8, "agent": "ceo_agent", "action": "generate_daily_report"},
                ],
            },
            "content_factory": {
                "name": "内容工厂流水线",
                "steps": [
                    {"order": 1, "agent": "trend_agent", "action": "discover_content_topics"},
                    {"order": 2, "agent": "content_agent", "action": "generate_content_batch"},
                    {"order": 3, "agent": "video_agent", "action": "generate_video_scripts"},
                    {"order": 4, "agent": "heygen_agent", "action": "produce_digital_human_videos"},
                    {"order": 5, "agent": "brand_agent", "action": "localize_content"},
                    {"order": 6, "agent": "community_agent", "action": "publish_content_matrix"},
                ],
            },
            "alliance_growth": {
                "name": "联盟裂变流水线",
                "steps": [
                    {"order": 1, "agent": "affiliate_agent", "action": "recruit_affiliates"},
                    {"order": 2, "agent": "kol_agent", "action": "discover_kols"},
                    {"order": 3, "agent": "referral_agent", "action": "activate_referral_program"},
                    {"order": 4, "agent": "partner_agent", "action": "onboard_partners"},
                    {"order": 5, "agent": "training_agent", "action": "train_alliance_members"},
                    {"order": 6, "agent": "community_agent", "action": "engage_community"},
                    {"order": 7, "agent": "ecosystem_agent", "action": "report_alliance_growth"},
                ],
            },
            "amazon_listing_optimization": {
                "name": "Amazon Listing优化",
                "steps": [
                    {"order": 1, "agent": "amazon_manager_agent", "action": "init_listing_project"},
                    {"order": 2, "agent": "amazon_listing_agent", "action": "generate_listing"},
                    {"order": 3, "agent": "localization_agent", "action": "localize_listing"},
                ],
            },
            "amazon_ppc_optimization": {
                "name": "Amazon PPC优化",
                "steps": [
                    {"order": 1, "agent": "amazon_ppc_agent", "action": "analyze_keywords"},
                    {"order": 2, "agent": "amazon_manager_agent", "action": "optimize_bids"},
                    {"order": 3, "agent": "analytics_agent", "action": "report_ppc_roi"},
                ],
            },
            "amazon_review_management": {
                "name": "Amazon Review管理",
                "steps": [
                    {"order": 1, "agent": "amazon_review_agent", "action": "analyze_review"},
                    {"order": 2, "agent": "amazon_manager_agent", "action": "handle_negative_review", "condition": "sentiment == 'negative'"},
                ],
            },
            "shopify_launch": {
                "name": "Shopify独立站上线",
                "steps": [
                    {"order": 1, "agent": "brand_agent", "action": "define_brand"},
                    {"order": 2, "agent": "shopify_agent", "action": "build_site"},
                    {"order": 3, "agent": "content_agent", "action": "create_product_pages"},
                    {"order": 4, "agent": "seo_agent", "action": "optimize_seo"},
                ],
            },
            "abandoned_cart_recovery": {
                "name": "弃购挽回",
                "steps": [
                    {"order": 1, "agent": "email_marketing_agent", "action": "send_cart_email"},
                    {"order": 2, "agent": "retention_agent", "action": "send_whatsapp_reminder", "condition": "email_not_opened == true"},
                ],
            },
            "tiktok_live_automation": {
                "name": "TikTok直播自动化",
                "steps": [
                    {"order": 1, "agent": "tiktok_shop_agent", "action": "select_live_products"},
                    {"order": 2, "agent": "content_agent", "action": "generate_live_script"},
                    {"order": 3, "agent": "heygen_agent", "action": "produce_live_avatar"},
                ],
            },
            "tiktok_kol_campaign": {
                "name": "TikTok达人合作",
                "steps": [
                    {"order": 1, "agent": "kol_agent", "action": "discover_kols"},
                    {"order": 2, "agent": "tiktok_shop_agent", "action": "verify_kol_fit"},
                    {"order": 3, "agent": "whatsapp_agent", "action": "outreach_kol"},
                    {"order": 4, "agent": "logistics_agent", "action": "send_samples", "condition": "kol_accepted == true"},
                ],
            },
            "inventory_forecast": {
                "name": "库存预测",
                "steps": [
                    {"order": 1, "agent": "demand_forecast_agent", "action": "forecast_demand"},
                    {"order": 2, "agent": "inventory_agent", "action": "generate_replenishment"},
                    {"order": 3, "agent": "procurement_agent", "action": "create_po", "condition": "stock_below_threshold == true"},
                ],
            },
            "logistics_routing": {
                "name": "物流路由优化",
                "steps": [
                    {"order": 1, "agent": "logistics_agent", "action": "compare_carriers"},
                    {"order": 2, "agent": "dhl_agent", "action": "get_quote"},
                    {"order": 3, "agent": "ups_agent", "action": "get_quote"},
                    {"order": 4, "agent": "fedex_agent", "action": "get_quote"},
                    {"order": 5, "agent": "logistics_agent", "action": "select_and_ship"},
                ],
            },
            "brand_globalization_v2": {
                "name": "品牌出海全流程V2",
                "steps": [
                    {"order": 1, "agent": "market_agent", "action": "full_market_scan"},
                    {"order": 2, "agent": "competitor_agent", "action": "competitor_analysis"},
                    {"order": 3, "agent": "brand_agent", "action": "brand_positioning"},
                    {"order": 4, "agent": "product_agent", "action": "localize_product"},
                    {"order": 5, "agent": "content_agent", "action": "build_content_matrix"},
                    {"order": 6, "agent": "heygen_agent", "action": "produce_brand_videos"},
                    {"order": 7, "agent": "ads_agent", "action": "launch_multi_channel"},
                    {"order": 8, "agent": "lead_agent", "action": "mine_customers"},
                    {"order": 9, "agent": "sdr_agent", "action": "outreach"},
                    {"order": 10, "agent": "sales_agent", "action": "close_deals"},
                    {"order": 11, "agent": "order_agent", "action": "process_orders"},
                    {"order": 12, "agent": "logistics_agent", "action": "fulfill"},
                    {"order": 13, "agent": "customer_success_agent", "action": "onboarding"},
                    {"order": 14, "agent": "retention_agent", "action": "retention_loop"},
                    {"order": 15, "agent": "franchise_agent", "action": "expand_channels"},
                ],
            },
            "ainails_full_chain": {
                "name": "AI NAILS全链路运营",
                "steps": [
                    {"order": 1, "agent": "ainails_location_agent", "action": "score_location"},
                    {"order": 2, "agent": "ainails_device_agent", "action": "deploy_device"},
                    {"order": 3, "agent": "logistics_agent", "action": "ship_device"},
                    {"order": 4, "agent": "ainails_device_agent", "action": "activate"},
                    {"order": 5, "agent": "store_growth_agent", "action": "growth_campaign"},
                    {"order": 6, "agent": "community_agent", "action": "community_launch"},
                    {"order": 7, "agent": "referral_agent", "action": "referral_program"},
                ],
            },
        }

    def on_complete(self, flow_id: str, callback: Callable):
        """注册完成回调"""
        if flow_id not in self._callbacks:
            self._callbacks[flow_id] = []
        self._callbacks[flow_id].append(callback)

    async def execute(self, flow_id: str, input_data: dict = None) -> dict:
        """执行TaskFlow"""
        flow_def = self._flow_definitions.get(flow_id)
        if not flow_def:
            return {"error": f"TaskFlow not found: {flow_id}"}

        execution = FlowExecution(
            flow_id=flow_id,
            status=FlowStatus.RUNNING,
            started_at=datetime.now(),
        )
        self._flows[flow_id] = execution

        logger.info(f"[TaskFlow] Starting: {flow_id} ({flow_def['name']}) with {len(flow_def['steps'])} steps")

        input_data = input_data or {}
        flow_context = {**input_data}

        for step_def in flow_def["steps"]:
            order = step_def["order"]
            agent_id = step_def["agent"]
            action = step_def["action"]
            condition = step_def.get("condition")

            # 检查条件
            if condition and not self._evaluate(condition, flow_context):
                step_result = StepResult(
                    order=order, agent_id=agent_id, action=action,
                    status=StepStatus.SKIPPED,
                    result={"reason": f"Condition not met: {condition}"},
                )
                execution.steps.append(step_result)
                logger.info(f"  Step {order}: SKIPPED ({agent_id}.{action}) - condition: {condition}")
                continue

            # 执行步骤
            step_start = datetime.now()
            step_result = StepResult(
                order=order, agent_id=agent_id, action=action,
                status=StepStatus.RUNNING,
            )

            try:
                if self.runtime:
                    # 使用AgentRuntimeV2执行
                    result = await self.runtime.execute_agent(agent_id, action, flow_context)
                    step_result.result = result
                    step_result.status = StepStatus.COMPLETED if result.get("status") == "completed" else StepStatus.FAILED
                else:
                    # 模拟执行
                    step_result.result = {
                        "agent_id": agent_id, "action": action, "status": "completed",
                        "result": f"Executed {action} successfully",
                    }
                    step_result.status = StepStatus.COMPLETED

                # 合并结果到上下文
                if isinstance(step_result.result.get("result"), dict):
                    flow_context.update(step_result.result["result"])
                flow_context[f"{agent_id}_result"] = step_result.result

            except Exception as e:
                step_result.status = StepStatus.FAILED
                step_result.error = str(e)
                logger.error(f"  Step {order}: FAILED ({agent_id}.{action}) - {e}")

                # 重试逻辑
                if execution.retry_count < execution.max_retries:
                    execution.retry_count += 1
                    logger.info(f"  Retrying step {order}... (attempt {execution.retry_count})")
                    try:
                        await asyncio.sleep(2)
                        if self.runtime:
                            result = await self.runtime.execute_agent(agent_id, action, flow_context)
                            step_result.result = result
                            step_result.status = StepStatus.COMPLETED
                            step_result.error = ""
                        else:
                            step_result.status = StepStatus.COMPLETED
                    except Exception as retry_e:
                        step_result.error = str(retry_e)

            step_result.duration_ms = (datetime.now() - step_start).total_seconds() * 1000
            execution.steps.append(step_result)

            if step_result.status == StepStatus.FAILED:
                execution.status = FlowStatus.FAILED
                break

            logger.info(f"  Step {order}: {step_result.status.value} ({agent_id}.{action}) - {step_result.duration_ms:.0f}ms")

        else:
            execution.status = FlowStatus.COMPLETED

        execution.completed_at = datetime.now()
        execution.total_duration_ms = (execution.completed_at - execution.started_at).total_seconds() * 1000

        logger.info(f"[TaskFlow] {flow_id}: {execution.status.value} in {execution.total_duration_ms:.0f}ms")

        # 触发回调
        if flow_id in self._callbacks:
            for cb in self._callbacks[flow_id]:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(execution)
                    else:
                        cb(execution)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        return {
            "flow_id": flow_id,
            "status": execution.status.value,
            "steps_completed": len([s for s in execution.steps if s.status == StepStatus.COMPLETED]),
            "steps_skipped": len([s for s in execution.steps if s.status == StepStatus.SKIPPED]),
            "steps_failed": len([s for s in execution.steps if s.status == StepStatus.FAILED]),
            "total_duration_ms": execution.total_duration_ms,
            "results": {s.agent_id: s.result for s in execution.steps},
        }

    def _evaluate(self, condition: str, context: dict) -> bool:
        """评估条件表达式"""
        try:
            parts = condition.split()
            if len(parts) >= 3:
                var_name, op, value = parts[0], parts[1], parts[2]

                # 在上下文中查找值
                actual = context.get(var_name)
                if actual is None:
                    # 搜索嵌套结果
                    for key, val in context.items():
                        if isinstance(val, dict):
                            actual = val.get(var_name) or val.get("result", {}).get(var_name)
                            if actual is not None:
                                break

                if actual is not None:
                    if op == ">=": return float(actual) >= float(value)
                    if op == "<=": return float(actual) <= float(value)
                    if op == ">": return float(actual) > float(value)
                    if op == "<": return float(actual) < float(value)
                    if op == "==":
                        return str(actual).lower() == str(value).lower()
                    if op == "!=":
                        return str(actual).lower() != str(value).lower()

            return True  # 默认通过
        except Exception:
            return True

    def get_execution(self, flow_id: str) -> Optional[dict]:
        """获取执行状态"""
        execution = self._flows.get(flow_id)
        if not execution:
            return None
        return {
            "flow_id": execution.flow_id,
            "status": execution.status.value,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "total_duration_ms": execution.total_duration_ms,
            "retry_count": execution.retry_count,
            "steps": [
                {
                    "order": s.order,
                    "agent_id": s.agent_id,
                    "action": s.action,
                    "status": s.status.value,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                }
                for s in execution.steps
            ],
        }

    def list_flows(self) -> list[dict]:
        """列出所有TaskFlow"""
        return [
            {"id": fid, "name": fdef["name"], "steps": len(fdef["steps"])}
            for fid, fdef in self._flow_definitions.items()
        ]
