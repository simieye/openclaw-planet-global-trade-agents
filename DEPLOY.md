# 🦞 龙虾星球共创联盟 - OpenClaw Agent Cluster 部署指南

## 系统概览

**龙虾星球共创联盟** 是一个基于 OpenClaw + AnyGen + HeyGen 的 AI 驱动全球商业生态操作系统。

| 组件 | 数量 | 说明 |
|------|------|------|
| **Agent 智能体** | 57 | 16个层级，覆盖董事会到设备执行 |
| **TaskFlow 流水线** | 14 | 端到端业务自动化流程 |
| **Webhook 路由** | 42 | 外部系统事件集成 |
| **知识库分类** | 10 | 企业级知识管理体系 |
| **SOP 文档** | 10 | 标准化操作流程体系 |

---

## 快速开始

### 前置条件
- Python 3.10+
- macOS / Linux
- (可选) Docker & Docker Compose

### 1. 克隆与安装

```bash
cd openclaw-agent-cluster

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实 API Key
```

### 2. 验证系统

```bash
# 查看系统状态
python orchestration/engine.py status

# 运行集成测试
python orchestration/engine.py test

# 列出所有 Agent
python orchestration/engine.py agents

# 列出所有 TaskFlow
python orchestration/engine.py taskflows
```

### 3. 启动引擎

```bash
# 启动完整引擎（含 HTTP Server）
python orchestration/engine.py serve --port 8080

# 或使用 macOS 启动器
python scripts/launch.py start

# 启动管理面板
python scripts/launch.py dashboard
```

### 4. macOS 开机自启

```bash
python scripts/launch.py install
```

---

## Agent 集群架构

### AI董事会 (10 Agents)
| Agent | 职责 |
|-------|------|
| Chairman Agent | 企业愿景、长期战略、重大决策 |
| CEO Agent | 战略执行、经营管理、全局调度 |
| COO Agent | 运营效率、流程优化、节点管理 |
| CFO Agent | 现金流分析、利润管理、全球分账 |
| CMO Agent | 品牌增长、用户增长、联盟营销 |
| CTO Agent | 技术架构、AI体系建设 |
| CRO Agent | 风险控制、合规管理 |
| Legal Agent | 合同审核、知识产权 |
| Investment Agent | 项目孵化、投资评估 |
| Innovation Agent | 新业务探索、AI创新 |

### 市场品牌层 (12 Agents)
Branding Agent, Market Agent, Trend Agent, KOL Agent, Affiliate Agent, Event Agent, Referral Agent, SEO Agent, Ads Agent, TikTok Shop Agent, Marketplace Agent

### 内容创意层 (5 Agents)
Content Agent, Video Agent, HeyGen Agent, Product Agent, Training Agent

### 销售成交流 (10 Agents)
Lead Agent, SDR Agent, Sales Agent, Proposal Agent, Quotation Agent, Contract Agent, Customer Success Agent, CRM Agent, Retention Agent, Churn Agent

### 龙虾星球生态层 (15 Agents)
Ecosystem Agent, Franchise Agent, Community Agent, City Node Agent, Partner Agent, Project Agent, Global Expansion Agent, 等

### AI NAILS设备层 (5 Agents)
Device Agent, Location Agent, Store Growth Agent, 等

### 财务供应链 (12 Agents)
Finance Agent, Accountant Agent, Invoice Agent, Payment Agent, Commission Agent, Order Agent, Inventory Agent, Procurement Agent, Logistics Agent, Production Agent, Quality Agent

---

## TaskFlow 流水线

| 流水线 | 步骤数 | 触发方式 |
|--------|--------|----------|
| 客户成交流水线 | 8 | Webhook + 手动 |
| 全球加盟裂变 | 10 | 定时 + Webhook |
| OPC项目共创 | 7 | Webhook |
| CEO经营驾驶舱 | 8 | 每日定时 |
| 全球扩张 | 7 | 定时 + 手动 |
| 全球分账 | 6 | 每日定时 |
| 品牌出海全流程 | 9 | 手动触发 |
| 内容工厂 | 6 | 每日定时 |
| 联盟裂变 | 7 | 每日定时 |
| AI NAILS设备运营 | 6 | Webhook |
| 电商运营 | 6 | 每日定时 |
| 工厂生产 | 6 | Webhook |
| 市场调研 | 3 | 每周定时 |
| 财务管理 | 4 | 每日定时 |

---

## Webhook 集成

42条Webhook路由覆盖以下系统：

- **CRM**: 新线索、客户画像、商机变更
- **邮件**: 询盘分析、回复分析
- **WhatsApp**: 消息接待、产品咨询
- **Shopify**: 订单、弃购、退款
- **Amazon**: 评论、订单、库存
- **TikTok Shop**: 订单、热视频、直播
- **ERP**: 库存、生产、采购、质检
- **支付**: Stripe、PayPal、退款
- **物流**: 发货、异常、签收
- **AI NAILS**: 设备上线、异常、交易
- **城市节点**: 申请、数据上报
- **加盟**: 申请、WhatsApp咨询
- **项目共创**: 提交、资源申请
- **合伙人**: 申请、推荐
- **社群**: 新成员、活动报名

---

## macOS 桌面管理

### 启动器命令

```bash
python scripts/launch.py start        # 启动完整引擎
python scripts/launch.py dashboard    # 启动管理面板
python scripts/launch.py status       # 查看系统状态
python scripts/launch.py test         # 运行集成测试
python scripts/launch.py agents       # 列出Agent
python scripts/launch.py deploy       # 部署外部集成
python scripts/launch.py install      # 安装开机自启
```

### 管理面板

启动后访问: `http://localhost:9080`

功能:
- 实时 Agent 状态监控
- TaskFlow 执行追踪
- Webhook 集成状态
- 生态系统健康度

---

## Docker 部署

```bash
docker-compose up -d
```

服务端口:
- 8080: OpenClaw Engine API
- 9080: 管理面板
- 9090: Prometheus 监控

---

## 环境变量

参考 `.env.example` 配置以下关键变量:

```bash
# LLM
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
GEMINI_API_KEY=xxx

# 业务系统
CRM_API_URL=xxx
ERP_API_URL=xxx
SHOPIFY_STORE_URL=xxx

# 支付
STRIPE_SECRET_KEY=sk_live_xxx
PAYPAL_CLIENT_ID=xxx

# 平台
ANYGEN_API_KEY=xxx
HEYGEN_API_KEY=xxx
```

---

## 龙虾星球 SOP 体系

| SOP | 内容 |
|-----|------|
| SOP 01 | 企业90天AI转型落地路线图 |
| SOP 02 | 企业100个Agent角色体系 |
| SOP 03 | 50个Webhook自动化工作流 |
| SOP 04 | 跨境工厂AI出海SOP |
| SOP 05 | TikTok Shop全球增长SOP |
| SOP 06 | Amazon品牌增长SOP |
| SOP 07 | Shopify DTC增长SOP |
| SOP 08 | AI NAILS全球加盟裂变SOP |
| SOP 09 | 龙虾星球联盟生态运营SOP |
| SOP 10 | 企业数字员工组织架构 |

---

## 增长飞轮

```
市场调研 → 品牌定位 → 内容工厂 → HeyGen视频
    ↓
全球获客 → 自动成交 → 订单交付 → 客户运营
    ↓
会员体系 → 代理裂变 → OPC共创 → IP生态
    ↓
全球扩张 → 城市节点 → 产业联盟 → 龙虾星球
```

---

## 技术支持

- OpenClaw Engine: `orchestration/engine.py`
- Agent 配置: `agents/`
- TaskFlow: `taskflows/taskflows.toml`
- Webhook: `webhooks/gateway.toml`
- 知识库: `knowledge/base.toml`
- 启动器: `scripts/launch.py`
