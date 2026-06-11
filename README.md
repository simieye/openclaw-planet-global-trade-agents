# 🦞 Simiaiclaw OS v5.3

## 一万个硅基大脑 · 全量调度操作系统 · SellerSprite 43 Tools · Amazon 全维度数据情报

[![Build DMG](https://github.com/simieye/openclaw-planet-global-trade-agents/actions/workflows/build-dmg.yml/badge.svg)](https://github.com/simieye/openclaw-planet-global-trade-agents/actions/workflows/build-dmg.yml)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-blue)](https://github.com/simieye/openclaw-planet-global-trade-agents/releases)
[![Version](https://img.shields.io/badge/version-5.3.0-orange)](https://github.com/simieye/openclaw-planet-global-trade-agents/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> 🚀 v5.3 重大升级：SellerSprite 卖家精灵 43 Tools 集成 · Amazon 全维度数据情报 · API/CLI/MCP/Agent 四种接入

---

## 📦 快速安装

### macOS 桌面应用 (推荐)

1. 前往 [Releases](https://github.com/simieye/openclaw-planet-global-trade-agents/releases) 下载最新 `龙虾星球共创联盟-*.dmg`
2. 双击打开 DMG，拖入 `Applications` 文件夹
3. 启动应用，自动启动 OpenClaw 引擎和管理驾驶舱

### 命令行部署

```bash
git clone https://github.com/simieye/openclaw-planet-global-trade-agents.git
cd openclaw-planet-global-trade-agents
pip install -r requirements.txt
python orchestration/engine.py status
```

---

## 🏗️ 系统架构

```
                     🦞 龙虾星球共创联盟
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    AI 董事会           AI 管理层          AI 执行层
    (10 Agents)        (15 Agents)       (32 Agents)
         │                  │                  │
         └──────────────────┼──────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         TaskFlow      Webhook       Knowledge
         (14条)        (42路由)      (10大类)
              │             │             │
              └─────────────┼─────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │         │        │        │         │
       CRM       ERP    Shopify  Amazon  TikTok Shop
         │         │        │        │         │
       WhatsApp  Email   Stripe  PayPal  AI NAILS
```

## 🤖 Agent 智能体集群 (57+)

| 层级 | Agent | 数量 |
|------|-------|------|
| 🏛️ AI董事会 | Chairman, CEO, COO, CFO, CMO, CTO, CRO, Legal, Investment, Innovation | 10 |
| 📊 市场品牌 | Market, Competitor, Trend, Branding, KOL, Affiliate, SEO, SEM | 8 |
| 🎨 内容创意 | Content, Video, HeyGen, Blog, Copywriting, Product | 6 |
| 💼 销售成交 | Lead, SDR, Sales, Proposal, Quotation, Contract, CRM | 7 |
| 🌍 龙虾星球生态 | Ecosystem, Franchise, Community, CityNode, Partner, Project, GlobalExpansion | 7 |
| 💅 AI NAILS | Device, Location, StoreGrowth | 3 |
| 🔧 供应链 | Inventory, Procurement, Logistics, Production, Quality | 5 |
| 💰 财务 | Finance, Accountant, Invoice, Payment, Commission, Cashflow | 6 |
| 📞 客服 | Support, FAQ, Ticket, Review, Retention, Churn | 6 |

## ⚡ TaskFlow 业务流水线 (14)

1. **客户成交流水线** — 从线索到成交全流程自动化
2. **全球加盟裂变流水线** — 加盟线索→评分→招商→签约→培训→上线
3. **OPC项目共创流水线** — 项目提交→评审→资源匹配→执行→分配
4. **CEO经营驾驶舱** — 每日汇总所有业务线数据
5. **全球扩张流水线** — 市场分析→合规→节点建设→运营
6. **全球分账流水线** — 收入→计算→分账→结算→对账
7. **品牌出海全流程** — 市场调研→内容→广告→获客端到端
8. **内容工厂流水线** — 选题→脚本→HeyGen视频→多语言→发布
9. **联盟裂变流水线** — 招募→评分→培训→激活→裂变
10. **AI NAILS设备运营** — 选址→投放→激活→运营→维护
11. **财务管理** — 收入→成本→利润→报表
12. **库存物流** — 订单→库存→采购→物流→交付
13. **客户运营** — 售后→满意度→复购→推荐
14. **广告优化** — 创建→测试→优化→扩量

## 🌐 Webhook 集成 (42)

| 系统 | 路由数 | 说明 |
|------|--------|------|
| CRM | 8 | 客户创建/更新/评分/流失 |
| 电商 | 6 | Shopify/Amazon/TikTok Shop 订单 |
| 社交通讯 | 6 | WhatsApp/Email/消息处理 |
| 支付 | 4 | Stripe/PayPal/分账 |
| 物流 | 3 | 发货/追踪/异常 |
| ERP | 3 | 库存/生产/采购 |
| AI NAILS | 3 | 设备/点位/运营 |
| 龙虾星球 | 5 | 加盟/城市/项目/合伙人/社群 |
| 其他 | 4 | CEO/报告/异常 |

## 🚀 快速开始

```bash
# 查看状态
make status

# 运行测试
make test-integration

# 列出所有 Agent
make agents

# 列出所有 TaskFlow
make taskflows

# 启动引擎
make serve

# 构建 DMG
bash scripts/build/build_dmg.sh
```

## 📋 SOP 体系 (10)

| SOP | 内容 |
|-----|------|
| SOP 01 | 企业90天AI转型落地路线图 |
| SOP 02 | 100个Agent角色体系 |
| SOP 03 | 50个Webhook自动化工作流 |
| SOP 04 | 跨境工厂AI出海 (OEM/ODM) |
| SOP 05 | TikTok Shop全球增长 |
| SOP 06 | Amazon品牌增长 |
| SOP 07 | Shopify独立站DTC增长 |
| SOP 08 | AI NAILS全球加盟裂变 |
| SOP 09 | 龙虾星球联盟生态运营 |
| SOP 10 | 企业数字员工组织架构 |

## 🛠️ 技术栈

- **调度引擎**: Python 3.10+ (asyncio)
- **配置管理**: TOML
- **LLM 接入**: OpenAI / Claude / Gemini / DeepSeek / Qwen
- **桌面应用**: Electron 33 (macOS / Windows / Linux)
- **Web 管理**: HTML5 + CSS3 + Vanilla JS
- **打包分发**: electron-builder (DMG / NSIS / AppImage)
- **CI/CD**: GitHub Actions
- **自动更新**: electron-updater (GitHub Releases)

## 📄 许可证

MIT License — 龙虾星球共创联盟

---

<p align="center">
  <b>🦞 龙虾星球共创联盟</b><br>
  <sub>OpenClaw Agent Cluster · AnyGen Workspace · HeyGen Digital Human Factory</sub><br>
  <sub>AI 驱动的全球跨境电商品牌出海增长飞轮</sub>
</p>
