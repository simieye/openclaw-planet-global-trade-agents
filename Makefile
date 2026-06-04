# OpenClaw Agent Cluster - Makefile
# 常用操作快捷命令

.PHONY: help install test status agents taskflows start serve docker-build docker-up docker-down clean lint \
        build-dmg build-icons release setup-env unified-status unified-agents unified-taskflows unified-serve unified-test

# 默认目标
help:
	@echo "🦞 龙虾星球共创联盟 - OpenClaw 智能体集群系统"
	@echo ""
	@echo "Usage:"
	@echo "  make install         Install Python dependencies"
	@echo "  make test            Run tests"
	@echo "  make test-integration Run integration test"
	@echo "  make status          Show cluster status"
	@echo "  make agents          List all agents"
	@echo "  make taskflows       List all taskflows"
	@echo "  make start           Start engine (CLI mode)"
	@echo "  make serve           Start HTTP server"
	@echo "  make build-icons     Generate app icons"
	@echo "  make build-dmg       Build macOS DMG installer"
	@echo "  make docker-build    Build Docker image"
	@echo "  make docker-up       Start with Docker Compose"
	@echo "  make docker-down     Stop Docker Compose"
	@echo "  make clean           Clean temp files"
	@echo "  make lint            Run linter"
	@echo "  make setup-env       Setup .env config"

# 安装依赖
install:
	pip install -r requirements.txt

# 运行测试
test:
	python -m pytest tests/ -v --tb=short 2>/dev/null || python -m unittest discover tests -v

# 集成测试
test-integration:
	python orchestration/engine.py test

# 查看状态
status:
	python orchestration/engine.py status

# 列出Agent
agents:
	python orchestration/engine.py agents

# 列出TaskFlow
taskflows:
	python orchestration/engine.py taskflows

# 启动引擎
start:
	python orchestration/engine.py start --no-scheduler

# 启动HTTP服务器
serve:
	python orchestration/engine.py serve --host 0.0.0.0 --port 8080

# ============================================================
# Unified Engine v3 (unified_engine.py)
# ============================================================

# 统一引擎 - 查看状态
unified-status:
	python orchestration/unified_engine.py status

# 统一引擎 - 列出Agent
unified-agents:
	python orchestration/unified_engine.py agents

# 统一引擎 - 列出TaskFlow
unified-taskflows:
	python orchestration/unified_engine.py taskflows

# 统一引擎 - 启动HTTP服务器
unified-serve:
	python orchestration/unified_engine.py serve --host 0.0.0.0 --port 8080

# 统一引擎 - 集成测试
unified-test:
	python orchestration/unified_engine.py test

# 统一引擎 - 执行TaskFlow
unified-execute:
	@if [ -z "$(TF)" ]; then \
		echo "Usage: make unified-execute TF=<taskflow_id>"; \
		exit 1; \
	fi
	python orchestration/unified_engine.py execute $(TF)

# 统一引擎 - 触发Agent
unified-trigger:
	@if [ -z "$(AGENT)" ] || [ -z "$(ACTION)" ]; then \
		echo "Usage: make unified-trigger AGENT=<agent_id> ACTION=<action>"; \
		exit 1; \
	fi
	python orchestration/unified_engine.py agent $(AGENT) --action $(ACTION)

# 启动CLI工具
cli:
	python scripts/cli.py status

# 执行TaskFlow
execute:
	@if [ -z "$(TF)" ]; then \
		echo "Usage: make execute TF=<taskflow_id>"; \
		exit 1; \
	fi
	python orchestration/engine.py execute $(TF)

# 触发Agent
trigger:
	@if [ -z "$(AGENT)" ] || [ -z "$(ACTION)" ]; then \
		echo "Usage: make trigger AGENT=<agent_id> ACTION=<action>"; \
		exit 1; \
	fi
	python orchestration/engine.py agent $(AGENT) --action $(ACTION)

# Docker构建
docker-build:
	docker build -t openclaw-engine:latest -f deploy/Dockerfile .

# Docker启动
docker-up:
	docker compose -f deploy/docker-compose.yml up -d

# Docker停止
docker-down:
	docker compose -f deploy/docker-compose.yml down

# Docker日志
docker-logs:
	docker logs -f openclaw-engine

# 清理
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf exported_config 2>/dev/null || true

# 代码检查
lint:
	python -m flake8 orchestration/ tests/ scripts/ --max-line-length=120 --ignore=E501,W503 2>/dev/null || echo "flake8 not installed, skipping"

# 导出配置
export-config:
	python scripts/cli.py export

# 环境配置
setup-env:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example - please edit with your actual keys"; \
	else \
		echo ".env already exists"; \
	fi

# 构建图标
build-icons:
	python3 scripts/build/generate_icons.py

# 构建 DMG
build-dmg:
	bash scripts/build/build_dmg.sh

# 完整发布流程
release: clean build-icons build-dmg
	@echo "🦞 Release build complete!"
	@echo "Check release/ directory for DMG file"
