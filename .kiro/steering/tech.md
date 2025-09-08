# Technology Stack

## Languages & Frameworks
- **Python 3.11+**: Primary language for both server and worker
- **FastAPI**: Web framework for the server component
- **Uvicorn**: ASGI server for running FastAPI applications
- **yt-dlp**: Core library for downloading videos from various platforms

## Cloud Services (Google Cloud Platform)
- **Google Cloud Pub/Sub**: Message queue for communication between server and worker
- **Google Cloud Storage**: File storage with signed URL generation
- **Google Cloud Run**: Serverless deployment platform for the server

## Key Dependencies
### Server (yt-dlp-server)
- `fastapi==0.104.1` - Web framework
- `uvicorn[standard]==0.24.0` - ASGI server
- `google-cloud-pubsub==2.19.0` - Pub/Sub client
- `google-cloud-storage` - GCS client (via worker dependencies)
- `python-dotenv==1.0.0` - Environment variable management
- `httpx==0.25.2` - HTTP client
- `jinja2==3.1.2` - Template engine

### Worker (yt-dlp-worker)
- `yt-dlp==2023.7.6` - Video downloader
- `google-cloud-pubsub==2.19.0` - Pub/Sub subscriber
- `google-cloud-storage==2.10.0` - Cloud storage client
- `python-dotenv==0.21.0` - Environment configuration

## Build System & Commands

### Environment Setup
```bash
# Setup both components
make setup

# Setup individual components
make setup-worker
make setup-server
```

### Development
```bash
# Run components locally
make run-worker    # Start worker process
make run-server    # Start server with auto-reload

# Testing
make test-worker   # Run worker tests
make test-server   # Run server tests (not implemented yet)
```

### Docker Development
```bash
# Development with hot reload
make docker-dev    # Build and run with code mounting

# Production builds
make docker-build  # Build production image
make docker-run    # Run production container
```

### Deployment
```bash
# Google Cloud Run deployment
make deploy

# Local Docker deployment
make deploy-local
```

### Utilities
```bash
# Environment management
make check-env     # Verify setup
make install-deps  # Update dependencies
make clean         # Remove build artifacts

# Cookie management
make export-cookies # Export browser cookies for authentication

# Storage management
make clear-uploads           # Clear all uploaded files
make clear-old DAYS=7       # Clear files older than X days
```

## Development Environment
- **Virtual Environments**: `.venv_3.13.0` for both components
- **Environment Files**: `.env` files for configuration
- **Service Account**: `yt-dlp-worker-key.json` for GCP authentication
- **Cookies**: `cookies.txt` for platform authentication

## Architecture Patterns
- **Microservices**: Separate server and worker components
- **Event-driven**: Pub/Sub messaging for decoupled communication
- **WebSocket**: Real-time progress updates to clients
- **Containerization**: Docker for consistent deployment
- **Cloud-native**: Designed for Google Cloud Platform