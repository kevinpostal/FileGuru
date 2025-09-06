# Makefile for yt-dlp-server Docker management

# Variables
IMAGE_NAME = yt-dlp-server
DEV_IMAGE_NAME = yt-dlp-server-dev
CONTAINER_NAME = yt-dlp-server-container
DEV_CONTAINER_NAME = yt-dlp-server-dev-container
PORT = 8080
DOCKERFILE_PATH = Dockerfile
DEV_DOCKERFILE_PATH = Dockerfile.dev
BUILD_CONTEXT = .
# Google Cloud service account key file path (adjust as needed)
GCP_KEY_FILE = yt-dlp-worker-key.json

# Default target
.PHONY: help
help:
	@echo "Available commands:"
	@echo "Production:"
	@echo "  build       - Build the production Docker image"
	@echo "  run         - Run the production container (detached)"
	@echo "  stop        - Stop the running container"
	@echo "  restart     - Restart the container"
	@echo "  logs        - Show container logs"
	@echo "  shell       - Open shell in running container"
	@echo "  clean       - Stop and remove container"
	@echo "  rebuild     - Clean, build, and run"
	@echo "  status      - Show container status"
	@echo ""
	@echo "Development:"
	@echo "  dev-build   - Build the development Docker image (optimized for caching)"
	@echo "  dev-run     - Run development container with code mounting and auto-reload"
	@echo "  dev-stop    - Stop the development container"
	@echo "  dev-restart - Restart the development container"
	@echo "  dev-logs    - Show development container logs"
	@echo "  dev-shell   - Open shell in development container"
	@echo "  dev-clean   - Stop and remove development container"
	@echo "  dev-rebuild - Clean, build, and run development container"

# Build the production Docker image
.PHONY: build
build:
	docker build -t $(IMAGE_NAME) -f $(DOCKERFILE_PATH) $(BUILD_CONTEXT)

# Build the development Docker image (optimized for caching)
.PHONY: dev-build
dev-build:
	docker build -t $(DEV_IMAGE_NAME) -f $(DEV_DOCKERFILE_PATH) $(BUILD_CONTEXT)

# Run the production container in detached mode
.PHONY: run
run:
	@if [ -f "$(GCP_KEY_FILE)" ]; then \
		echo "Using GCP service account key file: $(GCP_KEY_FILE)"; \
		docker run -d --name $(CONTAINER_NAME) -p $(PORT):8080 \
			-v "$(shell pwd)/$(GCP_KEY_FILE):/app/yt-dlp-worker-key.json:ro" \
			-e GOOGLE_APPLICATION_CREDENTIALS="/app/yt-dlp-worker-key.json" \
			$(IMAGE_NAME); \
	else \
		echo "GCP key file not found at $(GCP_KEY_FILE), using local credentials"; \
		docker run -d --name $(CONTAINER_NAME) -p $(PORT):8080 \
			$(IMAGE_NAME); \
	fi
	@echo "Production container started on http://localhost:$(PORT)"

# Run the development container with code mounting and auto-reload
.PHONY: dev-run
dev-run:
	@if [ -f "$(GCP_KEY_FILE)" ]; then \
		echo "Using GCP service account key file: $(GCP_KEY_FILE)"; \
		docker run -d --name $(DEV_CONTAINER_NAME) -p $(PORT):8080 \
			-v "$(shell pwd):/app:rw" \
			-v "$(shell pwd)/$(GCP_KEY_FILE):/app/yt-dlp-worker-key.json:ro" \
			-e GOOGLE_APPLICATION_CREDENTIALS="/app/yt-dlp-worker-key.json" \
			$(DEV_IMAGE_NAME); \
	else \
		echo "GCP key file not found at $(GCP_KEY_FILE), using local credentials"; \
		docker run -d --name $(DEV_CONTAINER_NAME) -p $(PORT):8080 \
			-v "$(shell pwd):/app:rw" \
			$(DEV_IMAGE_NAME); \
	fi
	@echo "Development container started on http://localhost:$(PORT) with code mounting and auto-reload"

# Stop the running production container
.PHONY: stop
stop:
	docker stop $(CONTAINER_NAME) || true

# Stop the running development container
.PHONY: dev-stop
dev-stop:
	docker stop $(DEV_CONTAINER_NAME) || true

# Restart the production container
.PHONY: restart
restart: stop run

# Restart the development container
.PHONY: dev-restart
dev-restart: dev-stop dev-run

# Show production container logs
.PHONY: logs
logs:
	docker logs -f $(CONTAINER_NAME)

# Show development container logs
.PHONY: dev-logs
dev-logs:
	docker logs -f $(DEV_CONTAINER_NAME)

# Open shell in running production container
.PHONY: shell
shell:
	docker exec -it $(CONTAINER_NAME) /bin/bash

# Open shell in running development container
.PHONY: dev-shell
dev-shell:
	docker exec -it $(DEV_CONTAINER_NAME) /bin/bash

# Stop and remove production container
.PHONY: clean
clean:
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true

# Stop and remove development container
.PHONY: dev-clean
dev-clean:
	docker stop $(DEV_CONTAINER_NAME) || true
	docker rm $(DEV_CONTAINER_NAME) || true

# Clean, build, and run production
.PHONY: rebuild
rebuild: clean build run

# Clean, build, and run development
.PHONY: dev-rebuild
dev-rebuild: dev-clean dev-build dev-run

# Show container status
.PHONY: status
status:
	@echo "Container status:"
	@docker ps -a --filter name=$(CONTAINER_NAME) --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	@docker ps -a --filter name=$(DEV_CONTAINER_NAME) --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Stop all containers (production and development)
.PHONY: stop-all
stop-all: stop dev-stop

# Clean all containers (production and development)
.PHONY: clean-all
clean-all: clean dev-clean

# Remove images (use with caution)
.PHONY: clean-images
clean-images: clean-all
	docker rmi $(IMAGE_NAME) || true
	docker rmi $(DEV_IMAGE_NAME) || true