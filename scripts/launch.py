"""
龙虾星球共创联盟 - macOS 桌面启动器
OpenClaw + AnyGen + HeyGen 集成部署管理面板
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
ORCHESTRATION_DIR = BASE_DIR / "orchestration"


class LobsterPlanetLauncher:
    """龙虾星球 macOS 桌面启动器"""

    def __init__(self):
        self.base_dir = BASE_DIR
        self.host = "0.0.0.0"
        self.port = 8080

    def banner(self):
        print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║       🦞  龙虾星球共创联盟  🦞                          ║
║      Lobster Planet Co-Creation Alliance                 ║
║                                                          ║
║      OpenClaw Agent Cluster  v3.0                        ║
║      AnyGen Workspace Integration                        ║
║      HeyGen Digital Human Factory                        ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

    def check_prerequisites(self):
        """检查前置条件"""
        print("🔍 检查系统环境...")
        issues = []

        # 检查 Python 版本
        py_version = sys.version_info
        if py_version < (3, 10):
            issues.append(f"Python 版本过低: {py_version.major}.{py_version.minor}，需要 3.10+")

        # 检查关键文件
        required_files = [
            "agents/registry.toml",
            "taskflows/taskflows.toml",
            "webhooks/gateway.toml",
            "orchestration/engine.py",
        ]
        for f in required_files:
            if not (self.base_dir / f).exists():
                issues.append(f"缺少文件: {f}")

        if issues:
            print("❌ 发现问题:")
            for i in issues:
                print(f"  - {i}")
            return False

        print("✅ 环境检查通过")
        return True

    def install_deps(self):
        """安装依赖"""
        print("📦 安装依赖...")
        req_file = self.base_dir / "requirements.txt"
        if req_file.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "--quiet"],
                           check=False)
            print("✅ 依赖安装完成")
        else:
            print("⚠️  未找到 requirements.txt")

    def start_engine(self, with_server: bool = True):
        """启动引擎"""
        self.banner()
        print(f"\n🚀 启动龙虾星球引擎...")
        print(f"   端口: {self.port}")
        print(f"   模式: {'全功能' if with_server else '核心引擎'}")
        print()

        os.chdir(str(self.base_dir))
        cmd = [sys.executable, "orchestration/engine.py", "serve", "--port", str(self.port)]

        try:
            subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            print("\n\n🛑 引擎已停止")
        except Exception as e:
            print(f"\n❌ 引擎启动失败: {e}")

    def show_status(self):
        """显示状态"""
        os.chdir(str(self.base_dir))
        subprocess.run([sys.executable, "orchestration/engine.py", "status"], check=False)

    def run_test(self):
        """运行测试"""
        os.chdir(str(self.base_dir))
        subprocess.run([sys.executable, "orchestration/engine.py", "test"], check=False)

    def list_agents(self):
        """列出Agent"""
        os.chdir(str(self.base_dir))
        subprocess.run([sys.executable, "orchestration/engine.py", "agents"], check=False)

    def list_taskflows(self):
        """列出TaskFlow"""
        os.chdir(str(self.base_dir))
        subprocess.run([sys.executable, "orchestration/engine.py", "taskflows"], check=False)

    def start_dashboard(self):
        """启动管理面板"""
        self.banner()
        print("\n📊 启动龙虾星球管理面板...")
        print(f"   访问地址: http://localhost:{self.port + 1000}")
        print()

        # 启动 FastAPI 服务器
        os.chdir(str(self.base_dir))

        try:
            from orchestration.server import run_server
            from orchestration.engine import OrchestrationEngine

            engine = OrchestrationEngine()
            engine.initialize(with_runtime=False, with_scheduler=False)

            import asyncio
            asyncio.run(
                asyncio.to_thread(
                    run_server, engine, self.host, self.port + 1000, ""
                )
            )
        except KeyboardInterrupt:
            print("\n\n🛑 面板已停止")
        except ImportError as e:
            print(f"❌ 缺少依赖: {e}")
            print("请运行: pip install fastapi uvicorn")

    def deploy_integrations(self):
        """部署外部系统集成"""
        print("\n🔗 部署外部系统集成...")
        print("-" * 40)

        integrations = [
            ("CRM系统", "webhooks/gateway.toml", "wh_crm_"),
            ("ERP系统", "webhooks/gateway.toml", "wh_erp_"),
            ("Shopify", "webhooks/gateway.toml", "wh_shopify_"),
            ("Amazon", "webhooks/gateway.toml", "wh_amazon_"),
            ("TikTok Shop", "webhooks/gateway.toml", "wh_tiktok_"),
            ("WhatsApp", "webhooks/gateway.toml", "wh_whatsapp_"),
            ("Email系统", "webhooks/gateway.toml", "wh_email_"),
            ("Stripe支付", "webhooks/gateway.toml", "wh_payment_stripe"),
            ("PayPal支付", "webhooks/gateway.toml", "wh_payment_paypal"),
            ("物流系统", "webhooks/gateway.toml", "wh_logistics_"),
            ("AI NAILS设备", "webhooks/gateway.toml", "wh_ainails_"),
            ("城市节点", "webhooks/gateway.toml", "wh_city_node_"),
            ("加盟系统", "webhooks/gateway.toml", "wh_franchise_"),
            ("OPC项目共创", "webhooks/gateway.toml", "wh_project_"),
            ("合伙人系统", "webhooks/gateway.toml", "wh_partner_"),
            ("社群运营", "webhooks/gateway.toml", "wh_community_"),
        ]

        for name, config, prefix in integrations:
            config_path = self.base_dir / config
            if config_path.exists():
                print(f"  ✅ {name:15s} - Webhook已配置")
            else:
                print(f"  ⚠️  {name:15s} - 配置文件缺失")

        print("-" * 40)
        print("💡 请在各业务系统中配置对应的 Webhook URL:")
        print(f"   http://your-server:{self.port}/hooks/<path>")
        print()

    def create_launch_agent(self):
        """创建 macOS LaunchAgent plist"""
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lobsterplanet.openclaw</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{self.base_dir}/orchestration/engine.py</string>
        <string>serve</string>
        <string>--port</string>
        <string>8080</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{self.base_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{self.base_dir}/logs/openclaw.log</string>
    <key>StandardErrorPath</key>
    <string>{self.base_dir}/logs/openclaw_error.log</string>
</dict>
</plist>
"""
        plist_path = Path.home() / "Library/LaunchAgents/com.lobsterplanet.openclaw.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建日志目录
        logs_dir = self.base_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with open(plist_path, "w") as f:
            f.write(plist_content)

        print(f"\n✅ LaunchAgent 已创建: {plist_path}")
        print("\n📋 使用以下命令管理服务:")
        print(f"  启动: launchctl load {plist_path}")
        print(f"  停止: launchctl unload {plist_path}")
        print(f"  状态: launchctl list | grep lobsterplanet")


def main():
    parser = argparse.ArgumentParser(
        description="🦞 龙虾星球共创联盟 - macOS 桌面启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python launch.py start          启动完整引擎
  python launch.py dashboard      启动管理面板
  python launch.py status         查看系统状态
  python launch.py test           运行集成测试
  python launch.py deploy         部署外部集成
  python launch.py install        安装LaunchAgent（开机自启）
        """
    )

    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "dashboard", "status", "test", "agents",
                                 "taskflows", "deploy", "install", "check"])
    parser.add_argument("--port", type=int, default=8080, help="服务端口 (默认: 8080)")

    args = parser.parse_args()
    launcher = LobsterPlanetLauncher()
    launcher.port = args.port

    commands = {
        "start": lambda: launcher.start_engine(),
        "dashboard": lambda: launcher.start_dashboard(),
        "status": launcher.show_status,
        "test": launcher.run_test,
        "agents": launcher.list_agents,
        "taskflows": launcher.list_taskflows,
        "deploy": launcher.deploy_integrations,
        "install": launcher.create_launch_agent,
        "check": launcher.check_prerequisites,
    }

    func = commands.get(args.command)
    if func:
        func()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
