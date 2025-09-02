import os
import json
import asyncio
from typing import Dict, List
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import pubsub_v1
from google.auth import credentials
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Global variables to store WebSocket connections
active_connections: Dict[str, WebSocket] = {}
# For production, consider using Redis instead of in-memory storage

class DownloadRequest(BaseModel):
    url: str
    client_id: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Pub/Sub client
    app.state.publisher = pubsub_v1.PublisherClient(
        credentials=credentials.AnonymousCredentials()
        if os.getenv("ENV") == "local" 
        else None
    )
    app.state.topic_path = app.state.publisher.topic_path(
        os.getenv("PROJECT_ID"), 
        os.getenv("PUBSUB_TOPIC")
    )
    
    yield  # App runs here
    
    # Shutdown: Close all WebSocket connections
    for connection in active_connections.values():
        await connection.close()
    active_connections.clear()

app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "yt-dlp download server"}

@app.post("/submit")
async def submit_download_request(request: DownloadRequest, background_tasks: BackgroundTasks):
    # Validate URL format
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    # Publish message to Pub/Sub
    message_data = json.dumps({
        "url": request.url, 
        "client_id": request.client_id
    }).encode("utf-8")
    
    try:
        future = app.state.publisher.publish(
            app.state.topic_path, 
            data=message_data
        )
        future.result()  # Wait for publish to complete
        
        # Start background task to check if client is connected via WebSocket
        background_tasks.add_task(check_client_connection, request.client_id)
        
        return {"message": "Download request submitted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit request: {str(e)}")

async def check_client_connection(client_id: str):
    """Check if client has an active WebSocket connection"""
    await asyncio.sleep(1)  # Give client time to connect
    if client_id not in active_connections:
        print(f"Warning: Client {client_id} submitted request but has no active WebSocket connection")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    
    try:
        # Send immediate acknowledgment
        await websocket.send_json({
            "type": "connection",
            "message": "WebSocket connection established",
            "client_id": client_id
        })
        
        # Keep connection alive
        while True:
            # Wait for any message (just to keep connection open)
            data = await websocket.receive_text()
            # Optional: handle incoming messages from client
            if data == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        print(f"Client {client_id} disconnected")
    finally:
        # Clean up on disconnect
        if client_id in active_connections:
            del active_connections[client_id]

@app.post("/status/{client_id}")
async def update_status(client_id: str, status: dict):
    """Endpoint for the remote worker to send status updates"""
    if client_id in active_connections:
        try:
            await active_connections[client_id].send_json(status)
            return {"message": "Status update sent"}
        except Exception as e:
            # Remove stale connection
            del active_connections[client_id]
            return {"message": f"Failed to send update: {str(e)}"}
    else:
        return {"message": "No active connection for this client"}