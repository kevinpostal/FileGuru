# Project Structure

## Root Directory
```
├── Makefile                    # Main build orchestration
├── .gitignore                  # Git ignore patterns
├── yt-dlp-server/             # FastAPI web server component
└── yt-dlp-worker/             # Background worker component
```

## Server Component (yt-dlp-server/)
```
yt-dlp-server/
├── main.py                    # FastAPI application entry point
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Production container build
├── Dockerfile.dev            # Development container build
├── Makefile                  # Docker management commands
├── .env                      # Environment configuration
├── .dockerignore             # Docker build exclusions
├── yt-dlp-worker-key.json    # GCP service account key (gitignored)
├── static/                   # Static web assets (CSS, JS, images)
├── templates/                # Jinja2 HTML templates
├── .venv_3.13.0/            # Python virtual environment
└── __pycache__/             # Python bytecode cache
```

## Worker Component (yt-dlp-worker/)
```
yt-dlp-worker/
├── worker.py                 # Main worker process
├── requirements.txt          # Python dependencies
├── .env                     # Environment configuration
├── .gitignore               # Component-specific ignores
├── cookies.txt              # Browser cookies for authentication
├── cookies_template.txt     # Template for cookie format
├── COOKIES_README.md        # Cookie setup instructions
├── export_cookies.py        # Browser cookie extraction utility
├── test_auth.py            # Authentication testing
├── test_cookies.py         # Cookie validation testing
├── worker.log              # Worker process logs
├── yt-dlp-worker-key.json  # GCP service account key (gitignored)
├── logs/                   # Log file directory
├── .venv_3.13.0/          # Python virtual environment
└── __pycache__/           # Python bytecode cache
```

## Configuration Files

### Environment Variables (.env)
Both components use `.env` files for configuration:
- **Server**: API keys, Pub/Sub topics, project IDs
- **Worker**: GCS bucket names, subscription names, server URLs

### Service Account Keys
- `yt-dlp-worker-key.json` in both directories
- Used for Google Cloud authentication
- **Always gitignored** for security

### Virtual Environments
- `.venv_3.13.0/` directories contain isolated Python environments
- Created and managed via Makefiles
- Python 3.13.0 specifically targeted

## Key File Purposes

### Server Files
- `main.py`: FastAPI app with WebSocket endpoints, Pub/Sub publishing
- `static/`: Frontend assets (HTML, CSS, JavaScript)
- `templates/`: Jinja2 templates for web interface

### Worker Files
- `worker.py`: Pub/Sub subscriber, yt-dlp integration, GCS upload
- `cookies.txt`: Authentication cookies for private content
- `export_cookies.py`: Utility to extract cookies from browsers
- `test_*.py`: Testing utilities for authentication and cookies

## Build Artifacts
- `__pycache__/`: Python bytecode cache (gitignored)
- `*.log`: Log files (gitignored)
- `.venv*/`: Virtual environments (gitignored)

## Naming Conventions
- **Directories**: kebab-case (`yt-dlp-server`, `yt-dlp-worker`)
- **Python files**: snake_case (`main.py`, `export_cookies.py`)
- **Environment files**: lowercase (`.env`, `.dockerignore`)
- **Docker images**: kebab-case (`yt-dlp-server`, `yt-dlp-server-dev`)
- **GCP resources**: kebab-case (`yt-dlp-downloads`, `yt-dlp-downloads-sub`)

## Development Workflow
1. **Setup**: Use root `Makefile` for environment setup
2. **Development**: Run components separately with `make run-*`
3. **Testing**: Component-specific test files in worker directory
4. **Docker**: Use server `Makefile` for containerization
5. **Deployment**: Root `Makefile` handles cloud deployment