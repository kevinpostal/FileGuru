# Makefile for yt-dlp-server Docker management

# Variables
IMAGE_NAME = yt-dlp-server
CONTAINER_NAME = yt-dlp-server-container
PORT = 8080
DOCKERFILE_PATH = Dockerfile
BUILD_CONTEXT = .
# Google Cloud service account key file path (adjust as needed)
GCP_KEY_FILE = yt-dlp-worker-key.json

# Default target
.PHONY: help
help:
	@echo "Available commands:"
	@echo "  build    - Build the Docker image"
	@echo "  run      - Run the container (detached)"
	@echo "  stop     - Stop the running container"
	@echo "  restart  - Restart the container"
	@echo "  logs     - Show container logs"
	@echo "  shell    - Open shell in running container"
	@echo "  clean    - Stop and remove container"
	@echo "  rebuild  - Clean, build, and run"
	@echo "  status   - Show container status"

# Build the Docker image
.PHONY: build
build:
	docker build -t $(IMAGE_NAME) -f $(DOCKERFILE_PATH) $(BUILD_CONTEXT)

# Run the container in detached mode
.PHONY: run
run:
	@if [ ! -f "$(GCP_KEY_FILE)" ]; then \
		echo "Error: Google Cloud service account key file not found at $(GCP_KEY_FILE)"; \
		echo "Please ensure the key file exists or update GCP_KEY_FILE variable in Makefile"; \
		exit 1; \
	fi
	docker run -d --name $(CONTAINER_NAME) -p $(PORT):8080 \
		-v "$(shell pwd)/$(GCP_KEY_FILE):/app/yt-dlp-worker-key.json:ro" \
		$(IMAGE_NAME)
	@echo "Container started on http://localhost:$(PORT)"

# Stop the running container
.PHONY: stop
stop:
	docker stop $(CONTAINER_NAME) || true

# Restart the container
.PHONY: restart
restart: stop run

# Show container logs
.PHONY: logs
logs:
	docker logs -f $(CONTAINER_NAME)

# Open shell in running container
.PHONY: shell
shell:
	docker exec -it $(CONTAINER_NAME) /bin/bash

# Stop and remove container
.PHONY: clean
clean:
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true

# Clean, build, and run
.PHONY: rebuild
rebuild: clean build run

# Show container status
.PHONY: status
status:
	@echo "Container status:"
	@docker ps -a --filter name=$(CONTAINER_NAME) --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Remove image (use with caution)
.PHONY: clean-image
clean-image: clean
	docker rmi $(IMAGE_NAME) || true