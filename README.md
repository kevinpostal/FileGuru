# FileGuru 🎥

A distributed, cloud-native YouTube and social media downloader system built with FastAPI, yt-dlp, and Google Cloud Platform. Features real-time progress updates, multi-platform support, and secure cloud storage integration.

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)

## 🌟 Features

### Core Functionality
- **Multi-Platform Support**: YouTube, Instagram, TikTok, Twitter/X, and more
- **Real-Time Progress**: WebSocket-based live progress updates with fallback mechanisms
- **Cloud Storage Integration**: Automatic upload to Google Cloud Storage with signed URLs
- **URL Shortening**: TinyURL integration for easy link sharing
- **Cookie Authentication**: Support for private content via browser cookie extraction
- **Distributed Architecture**: Scalable server-worker design using Google Pub/Sub

### Technical Highlights
- **Matrix/Hacker Aesthetic**: Custom dark theme with green terminal styling
- **Progress Simulation**: Intelligent fallback progress generation when real progress is unavailable
- **Error Recovery**: Robust retry mechanisms and graceful error handling
- **Docker Support**: Full containerization for development and production
- **Auto-Cleanup**: Configurable file retention policies

## 🏗️ Architecture

### System Overview
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Web Browser   │    │   FastAPI Server │    │  Background     │
│                 │◄──►│                  │◄──►│  Worker         │
│ - Submit URLs   │    │ - WebSocket API  │    │ - yt-dlp        │
│ - Real-time UI  │    │ - Pub/Sub Pub    │    │ - GCS Upload    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │  Google Pub/Sub  │    │ Google Cloud    │
                       │                  │    │ Storage         │
                       │ - Message Queue  │    │ - File Storage  │
                       └──────────────────┘    └─────────────────┘
```

### Components

#### 🖥️ Server (`yt-dlp-server/`)
- **FastAPI** web application with WebSocket support
- Handles user interface and download requests
- Publishes jobs to Google Pub/Sub
- Manages real-time client connections
- Serves static assets with Matrix-themed UI

#### ⚙️ Worker (`yt-dlp-worker/`)
- Background processor using **yt-dlp**
- Subscribes to Pub/Sub messages
- Downloads videos with progress tracking
- Uploads files to Google Cloud Storage
- Sends status updates via WebSocket

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+**
- **Google Cloud Platform** account
- **Make** (for build automation)
- **Docker** (optional, for containerized deployment)

### 1. Clone Repository
```bash
git clone https://github.com/kevinpostal/FileGuru.git
cd FileGuru
```

### 2. Environment Setup
```bash
# Setup both components
make setup

# Or setup individually
make setup-worker
make setup-server
```

### 3. Configure Google Cloud
```bash
# Create service account key and place in both directories
# yt-dlp-worker/yt-dlp-worker-key.json
# yt-dlp-server/yt-dlp-worker-key.json

# Set up environment variables (see Configuration section)
```

### 4. Export Browser Cookies (Optional)
```bash
# For private content access
make export-cookies
```

### 5. Run Development Environment
```bash
# Terminal 1 - Start worker
make run-worker

# Terminal 2 - Start server
make run-server
```

Navigate to `http://localhost:8000` to access the web interface.

## ⚙️ Configuration

### Environment Variables

#### Server Configuration (`.env` in `yt-dlp-server/`)
```bash
PROJECT_ID=your-gcp-project-id
PUBSUB_TOPIC=yt-dlp-downloads
GOOGLE_APPLICATION_CREDENTIALS=./yt-dlp-worker-key.json
```

#### Worker Configuration (`.env` in `yt-dlp-worker/`)
```bash
PROJECT_ID=your-gcp-project-id
PUBSUB_SUBSCRIPTION=yt-dlp-downloads-sub
FASTAPI_URL=https://your-server-url/
GCS_BUCKET_NAME=your-bucket-name
GOOGLE_APPLICATION_CREDENTIALS=./yt-dlp-worker-key.json
LOG_LEVEL=INFO
DOWNLOAD_DIR=/tmp/downloads
COOKIES_FILE=cookies.txt
```

### Google Cloud Setup

1. **Create a GCP Project**
2. **Enable APIs**:
   - Cloud Pub/Sub API
   - Cloud Storage API
   - Cloud Run API (for deployment)

3. **Create Resources**:
   ```bash
   # Create Pub/Sub topic and subscription
   gcloud pubsub topics create yt-dlp-downloads
   gcloud pubsub subscriptions create yt-dlp-downloads-sub --topic=yt-dlp-downloads
   
   # Create storage bucket
   gsutil mb gs://your-bucket-name
   ```

4. **Service Account**:
   - Create service account with Pub/Sub and Storage permissions
   - Download JSON key file
   - Place in both component directories

## 🛠️ Development

### Available Commands

#### Environment Management
```bash
make setup           # Setup both environments
make check-env       # Verify configuration
make install-deps    # Update dependencies
make clean          # Remove build artifacts
```

#### Development
```bash
make run-worker     # Start worker process
make run-server     # Start server with auto-reload
make dev-both      # Instructions for running both
```

#### Testing
```bash
make test-worker   # Run worker tests
cd yt-dlp-worker && python test_auth.py    # Test authentication
cd yt-dlp-worker && python test_cookies.py # Test cookies
```

#### Docker Development
```bash
cd yt-dlp-server
make docker-dev    # Development with hot reload
make docker-build  # Production build
make docker-run    # Run production container
```

#### Utilities
```bash
make export-cookies           # Export browser cookies
make clear-uploads           # Clear all stored files
make clear-old DAYS=7        # Clear files older than 7 days
```

### Cookie Authentication

For accessing private content or bypassing bot detection:

1. **Automatic Export**:
   ```bash
   make export-cookies
   ```

2. **Manual Export**:
   - Use browser extension (e.g., "Get cookies.txt")
   - Export cookies for the target site
   - Save as `yt-dlp-worker/cookies.txt`

3. **Testing**:
   ```bash
   cd yt-dlp-worker
   python test_cookies.py
   ```

## 📦 Deployment

### Google Cloud Run (Recommended)

#### Server Deployment
```bash
make deploy
```

This will:
- Build container image
- Deploy to Google Cloud Run
- Configure environment variables
- Set up proper scaling

#### Worker Deployment
Deploy the worker as a separate Cloud Run service or Compute Engine instance:

```bash
# Build worker image
cd yt-dlp-worker
docker build -t gcr.io/PROJECT_ID/yt-dlp-worker .

# Deploy to Cloud Run
gcloud run deploy yt-dlp-worker \
  --image gcr.io/PROJECT_ID/yt-dlp-worker \
  --platform managed \
  --region us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --set-env-vars PROJECT_ID=your-project-id
```

### Local Docker Deployment
```bash
make deploy-local
```

### Production Considerations

1. **Scaling**: Configure Cloud Run autoscaling based on Pub/Sub queue depth
2. **Security**: Use IAM roles instead of service account keys in production
3. **Monitoring**: Set up Cloud Logging and Monitoring
4. **Storage**: Configure lifecycle policies for automatic cleanup
5. **Networking**: Use VPC if needed for internal communication

## 🎨 User Interface

### Features
- **Matrix-inspired design** with terminal aesthetics
- **Real-time progress bars** with smooth animations
- **Connection status indicators**
- **Download history** with automatic cleanup
- **Responsive design** for mobile devices
- **WebSocket connectivity** with automatic reconnection

### Supported Platforms
- YouTube (videos, playlists, shorts)
- Instagram (posts, stories, reels)
- TikTok (videos)
- Twitter/X (videos, spaces)
- And many more via yt-dlp

## 🔧 API Reference

### WebSocket Events

#### Client → Server
```javascript
// Download request
{
  "type": "download",
  "url": "https://youtube.com/watch?v=...",
  "client_id": "unique-client-id"
}
```

#### Server → Client
```javascript
// Progress update
{
  "type": "progress",
  "client_id": "unique-client-id",
  "progress": 45.2,
  "message": "Downloading...",
  "url": "https://youtube.com/watch?v=...",
  "metadata": {
    "speed": "1.2MB/s",
    "eta": "00:30",
    "file_size": "25.3MB"
  }
}

// Completion
{
  "type": "complete",
  "client_id": "unique-client-id",
  "download_url": "https://tinyurl.com/...",
  "file_name": "video_20231201_120000.mp4",
  "url": "https://youtube.com/watch?v=..."
}
```

### REST Endpoints

```bash
GET  /                    # Web interface
POST /api/health         # Health check
WS   /ws/{client_id}     # WebSocket connection
```

## 🛠️ Troubleshooting

### Common Issues

#### "No module named 'yt_dlp'"
```bash
make install-deps
```

#### "Failed to initialize Google Cloud clients"
- Verify service account key file exists
- Check `GOOGLE_APPLICATION_CREDENTIALS` path
- Ensure proper IAM permissions

#### "WebSocket connection failed"
- Check server is running on correct port
- Verify firewall settings
- Check browser console for errors

#### "Download stuck at 0%"
- Check worker logs: `tail -f yt-dlp-worker/worker.log`
- Verify Pub/Sub subscription is active
- Test with different URL

#### "Bot detection" or "Sign in to confirm you're not a bot"
- Export and configure cookies (see Cookie Authentication)
- Use VPN if region-blocked
- Try different video format

### Debug Commands
```bash
# Check environments
make check-env

# View logs
tail -f yt-dlp-worker/worker.log
tail -f yt-dlp-worker/progress_debug.log

# Test individual components
cd yt-dlp-worker && python -c "import worker; print('Worker OK')"
cd yt-dlp-server && python -c "import main; print('Server OK')"
```

## 📁 Project Structure

```
FileGuru/
├── Makefile                     # Main build orchestration
├── .gitignore                   # Git ignore patterns
├── README.md                    # This file
│
├── yt-dlp-server/              # FastAPI web server
│   ├── main.py                 # Application entry point
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Production container
│   ├── Dockerfile.dev          # Development container
│   ├── Makefile               # Docker commands
│   ├── .env                   # Environment config
│   ├── static/                # Web assets
│   │   ├── app.js            # Frontend JavaScript
│   │   ├── style.css         # Matrix-themed CSS
│   │   └── favicon.ico       # Site icon
│   └── templates/             # HTML templates
│       └── index.html        # Main interface
│
├── yt-dlp-worker/             # Background worker
│   ├── worker.py              # Main worker process
│   ├── requirements.txt       # Python dependencies
│   ├── .env                   # Environment config
│   ├── cookies.txt            # Browser cookies
│   ├── cookies_template.txt   # Cookie format template
│   ├── COOKIES_README.md      # Cookie setup guide
│   ├── export_cookies.py      # Cookie extraction utility
│   ├── test_auth.py          # Authentication tests
│   └── test_cookies.py       # Cookie validation
│
└── .kiro/                     # Project documentation
    └── steering/
        ├── product.md         # Product overview
        ├── tech.md           # Technical details
        └── structure.md      # Project structure
```

## 🤝 Contributing

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes**
4. **Test thoroughly**:
   ```bash
   make test-worker
   make check-env
   ```
5. **Commit your changes**: `git commit -m 'Add amazing feature'`
6. **Push to the branch**: `git push origin feature/amazing-feature`
7. **Open a Pull Request**

### Development Guidelines
- Follow PEP 8 for Python code
- Add tests for new features
- Update documentation as needed
- Use meaningful commit messages

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** - The powerful video downloader
- **[FastAPI](https://fastapi.tiangolo.com/)** - Modern web framework
- **Google Cloud Platform** - Infrastructure and services
- **Matrix Digital Rain** - Design inspiration

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/kevinpostal/FileGuru/issues)
- **Discussions**: [GitHub Discussions](https://github.com/kevinpostal/FileGuru/discussions)

---

<div align="center">
  
**[⬆ Back to Top](#fileguru-)**

Made with ❤️ by [kevinpostal](https://github.com/kevinpostal)

</div>
