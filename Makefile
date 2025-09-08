# Root Makefile for yt-dlp project management
# Manages both worker and server components

# Variables
PYTHON = python3
PIP = pip3
VENV_WORKER = yt-dlp-worker/.venv_3.13.0
VENV_SERVER = yt-dlp-server/.venv_3.13.0
WORKER_DIR = yt-dlp-worker
SERVER_DIR = yt-dlp-server

# Colors for output
GREEN = \033[0;32m
YELLOW = \033[1;33m
RED = \033[0;31m
NC = \033[0m # No Color

# Default target
.PHONY: help
help:
	@echo "$(GREEN)yt-dlp Project Management$(NC)"
	@echo ""
	@echo "$(YELLOW)Setup Commands:$(NC)"
	@echo "  setup           - Setup both worker and server environments"
	@echo "  setup-worker    - Setup worker environment only"
	@echo "  setup-server    - Setup server environment only"
	@echo ""
	@echo "$(YELLOW)Development Commands:$(NC)"
	@echo "  run-worker      - Run worker locally"
	@echo "  run-server      - Run server locally"
	@echo "  test-worker     - Run worker tests"
	@echo "  test-server     - Run server tests"
	@echo ""
	@echo "$(YELLOW)Service Commands:$(NC)"
	@echo "  start-worker    - Start worker as a background service"
	@echo "  stop-worker     - Stop worker background service"
	@echo "  status-worker   - Check status of worker background service"
	@echo "  logs-worker     - View background worker logs"
	@echo ""
	@echo "$(YELLOW)Docker Commands (Server):$(NC)"
	@echo "  docker-build    - Build server Docker image (production)"
	@echo "  docker-run      - Run server in Docker (production)"
	@echo "  docker-dev      - Build and run server in development mode with code mounting"
	@echo "  docker-stop     - Stop Docker container"
	@echo "  docker-logs     - Show Docker logs"
	@echo "  docker-clean    - Clean Docker resources"
	@echo ""
	@echo "$(YELLOW)Deployment Commands:$(NC)"
	@echo "  deploy          - Deploy server to Google Cloud Run"
	@echo "  deploy-local    - Deploy server locally with Docker"
	@echo ""
	@echo "$(YELLOW)Utility Commands:$(NC)"
	@echo "  clean           - Clean all build artifacts"
	@echo "  install-deps    - Install/update dependencies"
	@echo "  check-env       - Check environment setup"
	@echo "  export-cookies  - Export cookies from browser"
	@echo ""
	@echo "$(YELLOW)Google Storage Commands:$(NC)"
	@echo "  clear-uploads   - Clear all uploads from Google Storage bucket"
	@echo "  clear-old       - Clear uploads older than X days (usage: make clear-old DAYS=7)"

# Setup commands
.PHONY: setup
setup: setup-worker setup-server
	@echo "$(GREEN)✓ Both environments setup complete$(NC)"

.PHONY: setup-worker
setup-worker:
	@echo "$(YELLOW)Setting up worker environment...$(NC)"
	@cd $(WORKER_DIR) && $(PYTHON) -m venv .venv_3.13.0
	@cd $(WORKER_DIR) && .venv_3.13.0/bin/pip install -r requirements.txt
	@echo "$(GREEN)✓ Worker environment ready$(NC)"

.PHONY: setup-server
setup-server:
	@echo "$(YELLOW)Setting up server environment...$(NC)"
	@cd $(SERVER_DIR) && $(PYTHON) -m venv .venv_3.13.0
	@cd $(SERVER_DIR) && .venv_3.13.0/bin/pip install -r requirements.txt
	@echo "$(GREEN)✓ Server environment ready$(NC)"

# Development commands
.PHONY: run-worker
run-worker:
	@echo "$(YELLOW)Starting worker...$(NC)"
	@cd $(WORKER_DIR) && .venv_3.13.0/bin/python worker.py

.PHONY: run-server
run-server:
	@echo "$(YELLOW)Starting server...$(NC)"
	@cd $(SERVER_DIR) && .venv_3.13.0/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8080

# Service Commands
.PHONY: start-worker stop-worker status-worker logs-worker

start-worker:
	@echo "$(YELLOW)Starting worker service...$(NC)"
	@if [ -f worker.pid ]; then \
		echo "$(RED)Worker is already running.$(NC)"; \
	else \
		cd $(WORKER_DIR) && nohup ./.venv_3.13.0/bin/python worker.py > ../worker.log 2>&1 & echo $! > ../worker.pid; \
		echo "$(GREEN)✓ Worker service started.$(NC)"; \
	fi

stop-worker:
	@echo "$(YELLOW)Stopping worker service...$(NC)"
	@if [ -f worker.pid ]; then \
		kill `cat worker.pid`; \
		rm worker.pid; \
		echo "$(GREEN)✓ Worker service stopped.$(NC)"; \
	else \
		echo "$(RED)Worker is not running.$(NC)"; \
	fi

status-worker:
	@echo "$(YELLOW)Checking worker service status...$(NC)"
	@if [ -f worker.pid ]; then \
		if ps -p `cat worker.pid` > /dev/null; then \
			echo "$(GREEN)✓ Worker is running.$(NC)"; \
		else \
			echo "$(RED)✗ Worker is not running, but PID file exists.$(NC)"; \
		fi; \
	else \
		echo "$(RED)✗ Worker is not running.$(NC)"; \
	fi

logs-worker:
	@echo "$(YELLOW)Tailing worker logs... (Press Ctrl+C to exit)$(NC)"
	@tail -f worker.log

# Testing commands


.PHONY: test-worker
test-worker:
	@echo "$(YELLOW)Running worker tests...$(NC)"
	@cd $(WORKER_DIR) && .venv_3.13.0/bin/python test_cookies.py
	@cd $(WORKER_DIR) && .venv_3.13.0/bin/python test_auth.py

.PHONY: test-server
test-server:
	@echo "$(YELLOW)Running server tests...$(NC)"
	@echo "$(RED)No server tests configured yet$(NC)"

# Docker commands (delegate to server Makefile)
.PHONY: docker-build
docker-build:
	@echo "$(YELLOW)Building Docker image...$(NC)"
	@cd $(SERVER_DIR) && make build

.PHONY: docker-run
docker-run:
	@echo "$(YELLOW)Running Docker container...$(NC)"
	@cd $(SERVER_DIR) && make run

.PHONY: docker-dev
docker-dev:
	@echo "$(YELLOW)Building and running development Docker container with code mounting...$(NC)"
	@cd $(SERVER_DIR) && make dev-build && make dev-run-attached

.PHONY: docker-stop
docker-stop:
	@echo "$(YELLOW)Stopping Docker containers...$(NC)"
	@cd $(SERVER_DIR) && make stop-all

.PHONY: docker-logs
docker-logs:
	@cd $(SERVER_DIR) && make logs

.PHONY: docker-restart
docker-restart:
	@cd $(SERVER_DIR) && make restart

.PHONY: docker-clean
docker-clean:
	@echo "$(YELLOW)Cleaning Docker resources...$(NC)"
	@cd $(SERVER_DIR) && make clean-all

# Utility commands
.PHONY: clean
clean:
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.pyd" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

.PHONY: install-deps
install-deps:
	@echo "$(YELLOW)Installing/updating dependencies...$(NC)"
	@cd $(WORKER_DIR) && .venv_3.13.0/bin/pip install -r requirements.txt --upgrade
	@cd $(SERVER_DIR) && .venv_3.13.0/bin/pip install -r requirements.txt --upgrade
	@echo "$(GREEN)✓ Dependencies updated$(NC)"

.PHONY: check-env
check-env:
	@echo "$(YELLOW)Checking environment setup...$(NC)"
	@echo "Worker environment:"
	@if [ -d "$(WORKER_DIR)/.venv_3.13.0" ]; then \
		echo "  $(GREEN)✓ Virtual environment exists$(NC)"; \
	else \
		echo "  $(RED)✗ Virtual environment missing$(NC)"; \
	fi
	@if [ -f "$(WORKER_DIR)/.env" ]; then \
		echo "  $(GREEN)✓ Environment file exists$(NC)"; \
	else \
		echo "  $(RED)✗ Environment file missing$(NC)"; \
	fi
	@if [ -f "$(WORKER_DIR)/cookies.txt" ]; then \
		echo "  $(GREEN)✓ Cookies file exists$(NC)"; \
	else \
		echo "  $(YELLOW)⚠ Cookies file missing$(NC)"; \
	fi
	@echo "Server environment:"
	@if [ -d "$(SERVER_DIR)/.venv_3.13.0" ]; then \
		echo "  $(GREEN)✓ Virtual environment exists$(NC)"; \
	else \
		echo "  $(RED)✗ Virtual environment missing$(NC)"; \
	fi
	@if [ -f "$(SERVER_DIR)/.env" ]; then \
		echo "  $(GREEN)✓ Environment file exists$(NC)"; \
	else \
		echo "  $(YELLOW)⚠ Environment file missing$(NC)"; \
	fi

.PHONY: export-cookies
export-cookies:
	@echo "$(YELLOW)Exporting cookies from browser...$(NC)"
	@cd $(WORKER_DIR) && .venv_3.13.0/bin/python export_cookies.py

# Development workflow shortcuts
.PHONY: dev-worker
dev-worker: setup-worker run-worker

.PHONY: dev-server
dev-server: setup-server run-server

.PHONY: dev-both
dev-both: setup
	@echo "$(YELLOW)Use 'make run-worker' and 'make run-server' in separate terminals$(NC)"

# Production deployment
.PHONY: deploy
deploy:
	@echo "$(YELLOW)Deploying to Google Cloud Run...$(NC)"
	@cd $(SERVER_DIR) && gcloud run deploy yt-dlp-server \
		--source . \
		--platform managed \
		--region us-central1 \
		--allow-unauthenticated \
		--set-env-vars="PROJECT_ID=hosting-shit,PUBSUB_TOPIC=yt-dlp-downloads,ENV=production"
	@echo "$(GREEN)✓ Deployment complete$(NC)"

# Local Docker deployment
.PHONY: deploy-local
deploy-local: docker-build docker-run
	@echo "$(GREEN)✓ Local Docker deployment complete$(NC)"

# Google Storage cleanup commands
.PHONY: clear-uploads
clear-uploads:
	@echo "$(YELLOW)Clearing all uploads from Google Storage bucket...$(NC)"
	@echo "$(RED)WARNING: This will delete ALL files in the bucket!$(NC)"
	@read -p "Are you sure? (y/N): " confirm && [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ] || (echo "$(YELLOW)Operation cancelled$(NC)" && exit 1)
	@if [ -f "$(WORKER_DIR)/.env" ]; then \
		export $$(cat $(WORKER_DIR)/.env | grep -v '^#' | xargs) && \
		gsutil -m rm -r gs://$$GCS_BUCKET_NAME/** 2>/dev/null || echo "$(YELLOW)Bucket already empty or no files to delete$(NC)"; \
	else \
		echo "$(RED)✗ Worker .env file not found$(NC)" && exit 1; \
	fi
	@echo "$(GREEN)✓ All uploads cleared from bucket$(NC)"

.PHONY: clear-old
clear-old:
	@if [ -z "$(DAYS)" ]; then \
		echo "$(RED)✗ Please specify DAYS parameter (e.g., make clear-old DAYS=7)$(NC)" && exit 1; \
	fi
	@echo "$(YELLOW)Clearing uploads older than $(DAYS) days from Google Storage bucket...$(NC)"
	@if [ -f "$(WORKER_DIR)/.env" ]; then \
		export $$(cat $(WORKER_DIR)/.env | grep -v '^#' | xargs) && \
		echo "$(YELLOW)Finding files older than $(DAYS) days...$(NC)" && \
		gsutil ls -l gs://$$GCS_BUCKET_NAME/** | awk -v days=$(DAYS) 'BEGIN{cutoff=systime()-days*86400} {if($$2!="" && $$2<cutoff) print $$3}' > /tmp/old_files.txt 2>/dev/null || true && \
		if [ -s /tmp/old_files.txt ]; then \
			echo "$(YELLOW)Files to delete:$(NC)" && \
			cat /tmp/old_files.txt && \
			echo "$(YELLOW)Deleting files...$(NC)" && \
			cat /tmp/old_files.txt | xargs -r gsutil -m rm && \
			echo "$(GREEN)✓ Old files deleted$(NC)"; \
		else \
			echo "$(YELLOW)No files older than $(DAYS) days found$(NC)"; \
		fi && \
		rm -f /tmp/old_files.txt; \
	else \
		echo "$(RED)✗ Worker .env file not found$(NC)" && exit 1; \
	fi