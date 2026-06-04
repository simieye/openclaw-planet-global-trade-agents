#!/usr/bin/env python3
"""
OpenClaw Agent Cluster CLI 管理工具
统一命令行管理界面
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestration.engine import OrchestrationEngine, Event


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def print_banner():
    print(f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════╗
║     OpenClaw 跨境电商品牌出海智能体集群系统 v1.0          ║
╚══════════════════════════════════════════════════════════╝{Colors.END}
""")


def print_table(headers: list, rows: list, col_widths: list = None):
    """打印格式化表格"""
    if not col_widths:
        col_widths = [max(len(str(row[i])) for row in [headers] + rows) + 2 for i in range(len(headers))]

    # 打印表头
    header_line = "│ " + " │ ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " │"
    separator = "├─" + "─┼─".join("─" * w for w in col_widths) + "─┤"

    print("┌─" + "─┬─".join("─" * w for w in col_widths) + "─┐")
    print(header_line)
    print(separator)

    for row in rows:
        line = "│ " + " │ ".join(str(r).ljust(w) for r, w in zip(row, col_widths)) + " │"
        print(line)

    print("└─" + "─┴─".join("─" * w for w in col_widths) + "─┘")


async def cmd_status(engine: OrchestrationEngine):
    """显示集群状态"""
    status = engine.get_status()
    print_banner()

    print(f"{Colors.BOLD}Engine Status:{Colors.END} {Colors.GREEN if status['engine'] == 'running' else Colors.RED}{status['engine']}{Colors.END}")
    print(f"{Colors.BOLD}Total Agents:{Colors.END} {status['total_agents']}")
    print(f"{Colors.BOLD}Total TaskFlows:{Colors.END} {status['total_taskflows']}")
    print(f"{Colors.BOLD}Webhook Routes:{Colors.END} {status['total_webhook_routes']}")
    print()

    print(f"{Colors.BOLD}Agents by Layer:{Colors.END}")
    print("-" * 50)
    for layer, agents in status["agents_by_layer"].items():
        color = {
            "strategic": Colors.YELLOW,
            "market": Colors.BLUE,
            "product": Colors.GREEN,
            "content": Colors.CYAN,
            "sales": Colors.RED,
            "operations": Colors.BLUE,
            "finance": Colors.GREEN,
            "supply_chain": Colors.YELLOW,
        }.get(layer, "")
        print(f"  {color}[{layer.upper()}]{Colors.END}")
        for a in agents:
            status_color = Colors.GREEN if a['status'] == 'idle' else Colors.YELLOW
            print(f"    {a['id']:30s} {status_color}[{a['status']}]{Colors.END}")

    if "scheduler" in status:
        print(f"\n{Colors.BOLD}Scheduled Tasks:{Colors.END}")
        print("-" * 50)
        for t in status["scheduler"]["tasks"]:
            enabled = Colors.GREEN if t["enabled"] else Colors.RED
            print(f"  {enabled}{t['id']:40s}{Colors.END} cron='{t['cron']}'")


async def cmd_agents(engine: OrchestrationEngine, layer: str = None):
    """列出所有 Agent"""
    if layer:
        agents = engine.registry.get_by_layer(layer)
    else:
        agents = engine.registry.list_all()

    agents = sorted(agents, key=lambda a: (a.layer, a.priority))

    print(f"\n{Colors.BOLD}Registered Agents ({len(agents)}):{Colors.END}\n")

    headers = ["Layer", "Agent ID", "P", "Description"]
    rows = [
        [a.layer, a.id, str(a.priority), a.description]
        for a in agents
    ]
    print_table(headers, rows)


async def cmd_taskflows(engine: OrchestrationEngine):
    """列出所有 TaskFlow"""
    print(f"\n{Colors.BOLD}Registered TaskFlows:{Colors.END}\n")

    headers = ["Priority", "TaskFlow ID", "Steps", "Trigger", "Description"]
    rows = [
        [
            tf.priority,
            tf.id,
            str(len(tf.steps)),
            tf.trigger[:30],
            tf.description,
        ]
        for tf in engine.taskflow_engine.taskflows.values()
    ]
    print_table(headers, rows)


async def cmd_execute(engine: OrchestrationEngine, tf_id: str, input_json: str = None):
    """执行 TaskFlow"""
    input_data = {}
    if input_json:
        try:
            input_data = json.loads(input_json)
        except json.JSONDecodeError:
            print(f"{Colors.RED}Invalid JSON input{Colors.END}")
            return

    print(f"\n{Colors.BOLD}Executing TaskFlow: {tf_id}{Colors.END}")
    print("-" * 50)

    try:
        result = await engine.execute_taskflow(tf_id, input_data)
        print(f"\n{Colors.GREEN}TaskFlow completed successfully!{Colors.END}")
        print(f"\nResults:")
        for agent_id, step_result in result.items():
            status = step_result.get("status", "unknown")
            color = Colors.GREEN if status == "completed" else Colors.RED
            print(f"  {agent_id}: {color}{status}{Colors.END}")
    except ValueError as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")
        print(f"\nAvailable TaskFlows:")
        for tf_id in engine.taskflow_engine.taskflows:
            print(f"  - {tf_id}")


async def cmd_agent_trigger(engine: OrchestrationEngine, agent_id: str, action: str, data_json: str = None):
    """触发 Agent"""
    data = {}
    if data_json:
        try:
            data = json.loads(data_json)
        except json.JSONDecodeError:
            print(f"{Colors.RED}Invalid JSON data{Colors.END}")
            return

    print(f"\n{Colors.BOLD}Triggering Agent: {agent_id} action={action}{Colors.END}")
    print("-" * 50)

    try:
        result = await engine.execute_agent(agent_id, action, data)
        print(f"\n{Colors.GREEN}Agent executed!{Colors.END}")
        print(f"  Agent: {result.get('agent_id')}")
        print(f"  Status: {result.get('status')}")
        print(f"  Tokens: {result.get('tokens_used', 0)}")
        if result.get("error"):
            print(f"  Error: {result['error']}")
    except ValueError as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")


async def cmd_webhook_routes(engine: OrchestrationEngine):
    """列出 Webhook 路由"""
    print(f"\n{Colors.BOLD}Webhook Routes:{Colors.END}\n")

    for route in engine.webhook_gateway.routes:
        print(f"  {Colors.CYAN}{route.path}{Colors.END} ({route.source})")
        print(f"    {route.description}")
        for evt in route.events:
            print(f"    ├── {evt['name']} → {evt['action']}:{evt['target']}")
        print()


async def cmd_send_event(engine: OrchestrationEngine, source: str, event_name: str, data_json: str = None):
    """发送事件"""
    data = {}
    if data_json:
        try:
            data = json.loads(data_json)
        except json.JSONDecodeError:
            print(f"{Colors.RED}Invalid JSON data{Colors.END}")
            return

    event = Event(
        id=f"cli-{event_name}",
        source=source,
        name=event_name,
        data=data,
    )

    print(f"\n{Colors.BOLD}Sending Event: {source}/{event_name}{Colors.END}")
    result = await engine.dispatch_event(event)
    print(f"  Result: {json.dumps(result, indent=2, default=str, ensure_ascii=False)}")


async def cmd_export_config(engine: OrchestrationEngine, output_dir: str = None):
    """导出配置文件"""
    output_dir = output_dir or "exported_config"
    os.makedirs(output_dir, exist_ok=True)

    # 导出 Agent Registry
    registry_data = engine.loader.load_agent_registry()
    with open(f"{output_dir}/registry.json", "w") as f:
        json.dump(registry_data, f, indent=2, ensure_ascii=False)

    # 导出 TaskFlows
    tf_data = engine.loader.load_taskflows()
    with open(f"{output_dir}/taskflows.json", "w") as f:
        json.dump(tf_data, f, indent=2, ensure_ascii=False, default=str)

    # 导出 Webhook Routes
    wh_data = engine.loader.load_webhooks()
    with open(f"{output_dir}/webhooks.json", "w") as f:
        json.dump(wh_data, f, indent=2, ensure_ascii=False, default=str)

    print(f"{Colors.GREEN}Config exported to: {output_dir}/{Colors.END}")
    for f in os.listdir(output_dir):
        print(f"  - {f}")


async def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw Agent Cluster CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                    Show cluster status
  %(prog)s agents                    List all agents
  %(prog)s agents --layer sales      List sales agents
  %(prog)s taskflows                 List all taskflows
  %(prog)s execute customer_acquisition   Execute a taskflow
  %(prog)s agent ceo_agent --action daily_briefing  Trigger agent
  %(prog)s webhooks                  List webhook routes
  %(prog)s event shopify orders/create '{"order_id":"123"}'  Send event
  %(prog)s export                    Export config to JSON
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # status
    subparsers.add_parser("status", help="Show cluster status")

    # agents
    agents_parser = subparsers.add_parser("agents", help="List agents")
    agents_parser.add_argument("--layer", "-l", help="Filter by layer")

    # taskflows
    subparsers.add_parser("taskflows", help="List taskflows")

    # execute
    exec_parser = subparsers.add_parser("execute", help="Execute a taskflow")
    exec_parser.add_argument("taskflow_id", help="TaskFlow ID")
    exec_parser.add_argument("--input", "-i", help="JSON input data")

    # agent trigger
    agent_parser = subparsers.add_parser("agent", help="Trigger an agent")
    agent_parser.add_argument("agent_id", help="Agent ID")
    agent_parser.add_argument("--action", "-a", required=True, help="Action name")
    agent_parser.add_argument("--data", "-d", help="JSON data")

    # webhooks
    subparsers.add_parser("webhooks", help="List webhook routes")

    # event
    event_parser = subparsers.add_parser("event", help="Send an event")
    event_parser.add_argument("source", help="Event source")
    event_parser.add_argument("event_name", help="Event name")
    event_parser.add_argument("data", nargs="?", help="JSON data")

    # export
    export_parser = subparsers.add_parser("export", help="Export config")
    export_parser.add_argument("--output", "-o", help="Output directory")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host")
    serve_parser.add_argument("--port", "-p", type=int, default=8080, help="Port")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 初始化引擎
    base_path = Path(__file__).parent.parent
    engine = OrchestrationEngine(str(base_path))
    engine.initialize(with_runtime=(args.command in ("agent", "serve")), with_scheduler=True)

    # 路由命令
    if args.command == "status":
        await cmd_status(engine)
    elif args.command == "agents":
        await cmd_agents(engine, args.layer)
    elif args.command == "taskflows":
        await cmd_taskflows(engine)
    elif args.command == "execute":
        await cmd_execute(engine, args.taskflow_id, args.input)
    elif args.command == "agent":
        await cmd_agent_trigger(engine, args.agent_id, args.action, args.data)
    elif args.command == "webhooks":
        await cmd_webhook_routes(engine)
    elif args.command == "event":
        await cmd_send_event(engine, args.source, args.event_name, args.data)
    elif args.command == "export":
        await cmd_export_config(engine, args.output)
    elif args.command == "serve":
        await engine.start(with_server=True, host=args.host, port=args.port)


if __name__ == "__main__":
    asyncio.run(main())
