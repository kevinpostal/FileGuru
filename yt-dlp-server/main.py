import os
import json
import asyncio
import uuid
import logging
from typing import Dict, List
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from google.cloud import pubsub_v1
from google.auth import credentials
from google.oauth2 import service_account
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables
active_connections: Dict[str, WebSocket] = {}

class DownloadRequest(BaseModel):
    url: str
    client_id: str

async def ping_websockets(app: FastAPI):
    """Periodically send pings to keep WebSocket connections alive"""
    while True:
        await asyncio.sleep(10)
        disconnected_clients = []
        for client_id, connection in active_connections.items():
            try:
                await connection.send_json({"type": "ping"})
            except (WebSocketDisconnect, ConnectionResetError):
                disconnected_clients.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected_clients:
            if client_id in active_connections:
                del active_connections[client_id]
                logger.info(f"Removed stale WebSocket connection for client: {client_id}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - Initialize Google Cloud credentials
    creds = None

    # Try to load service account credentials from file, or use default
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if creds_path:
        logger.info(f"GOOGLE_APPLICATION_CREDENTIALS: {creds_path}")
        if os.path.exists(creds_path):
            logger.info(f"Loading service account credentials from: {creds_path}")
            try:
                creds = service_account.Credentials.from_service_account_file(creds_path)
                logger.info("Service account credentials loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load service account credentials: {e}")
                raise
        else:
            logger.error(f"Service account key file not found at: {creds_path}")
            raise FileNotFoundError(f"Service account key file not found at: {creds_path}")
    else:
        # Use default credentials (for Cloud Run)
        logger.info("Using default Google Cloud credentials")
        creds = None  # This will use Application Default Credentials

    app.state.publisher = pubsub_v1.PublisherClient(credentials=creds)
    app.state.topic_path = app.state.publisher.topic_path(
        os.getenv("PROJECT_ID"), os.getenv("PUBSUB_TOPIC")
    )
    
    # Start background task for WebSocket pings
    app.state.ping_task = asyncio.create_task(ping_websockets(app))
    
    yield  # App runs here
    
    # Shutdown
    app.state.ping_task.cancel()
    for connection in active_connections.values():
        await connection.close()
    active_connections.clear()

app = FastAPI(lifespan=lifespan)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    client_id = str(uuid.uuid4())
    return templates.TemplateResponse("index.html", {"request": request, "client_id": client_id})

@app.post("/submit")
async def submit_download_request(request: DownloadRequest):
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    message_data = json.dumps({"url": request.url, "client_id": request.client_id}).encode("utf-8")
    
    try:
        future = app.state.publisher.publish(app.state.topic_path, data=message_data)
        future.result()
        logger.info(f"Published message for client {request.client_id}")
        return {"message": "Download request submitted successfully"}
    except Exception as e:
        logger.error(f"Failed to publish message to topic {app.state.topic_path}: {e}")
        logger.error(f"Project ID: {os.getenv('PROJECT_ID')}, Topic: {os.getenv('PUBSUB_TOPIC')}")
        raise HTTPException(status_code=500, detail=f"Failed to submit request: {e}")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    logger.info(f"WebSocket connection established for client: {client_id}")
    
    try:
        await websocket.send_json({"type": "connection", "message": "WebSocket connection established"})
        while True:
            data = await websocket.receive_text()
            if data == '{"type":"pong"}':
                logger.info(f"Received pong from client: {client_id}")
            else:
                logger.info(f"Received message from {client_id}: {data}")

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected")
    finally:
        if client_id in active_connections:
            del active_connections[client_id]
            logger.info(f"WebSocket connection closed for client: {client_id}")

@app.post("/status/{client_id}")
async def update_status(client_id: str, status: dict):
    logger.info(f"Received status update for client {client_id}: {status}")
    if client_id in active_connections:
        try:
            await active_connections[client_id].send_json(status)
            logger.info(f"Sent status update to client {client_id}")
            return {"message": "Status update sent"}
        except Exception as e:
            logger.error(f"Failed to send status update to {client_id}: {e}")
            if client_id in active_connections:
                del active_connections[client_id]
            return {"message": f"Failed to send update: {e}"}
    else:
        logger.warning(f"No active WebSocket connection for client: {client_id}")
        return {"message": "No active connection for this client"}
