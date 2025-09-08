# Product Overview

This is a distributed YouTube/social media downloader system built with Python. The system consists of two main components:

## Architecture
- **yt-dlp-server**: FastAPI web server that provides a web interface and handles download requests
- **yt-dlp-worker**: Background worker that processes downloads using yt-dlp and uploads files to Google Cloud Storage

## Key Features
- Web-based interface for submitting download requests
- Real-time progress updates via WebSocket connections
- Support for multiple platforms (YouTube, Instagram, TikTok, Twitter/X)
- Automatic file upload to Google Cloud Storage with signed URLs
- URL shortening via TinyURL for easy sharing
- Cookie-based authentication for accessing private content
- Docker containerization for easy deployment

## Workflow
1. User submits a URL through the web interface
2. Server publishes the request to Google Pub/Sub
3. Worker processes the download using yt-dlp
4. Worker uploads the file to Google Cloud Storage
5. User receives a download link via WebSocket

The system is designed for Google Cloud deployment but can run locally with Docker.