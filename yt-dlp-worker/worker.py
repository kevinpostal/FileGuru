# worker.py
import os
import json
import subprocess
import tempfile
import shutil
import logging
from datetime import datetime
from google.cloud import pubsub_v1, storage
from google.auth import credentials
import requests
from urllib.parse import urlparse
import socket

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('yt-dlp-worker')

# Configuration
PROJECT_ID = os.getenv('PROJECT_ID', 'your-project-id')
SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION', 'download-worker-sub')
FASTAPI_URL = os.getenv('FASTAPI_URL', 'https://your-fastapi-url.com')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'your-bucket-name')
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/tmp/downloads')

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class DownloadWorker:
    def __init__(self):
        # Initialize Google Cloud clients
        if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
            # Use service account credentials if provided
            self.subscriber = pubsub_v1.SubscriberClient()
            self.storage_client = storage.Client()
        else:
            # Use default credentials (for testing/local development)
            self.subscriber = pubsub_v1.SubscriberClient(
                credentials=credentials.AnonymousCredentials()
            )
            self.storage_client = storage.Client(
                credentials=credentials.AnonymousCredentials()
            )
        
        self.bucket = self.storage_client.bucket(GCS_BUCKET_NAME)
        self.subscription_path = self.subscriber.subscription_path(
            PROJECT_ID, SUBSCRIPTION_NAME
        )
        
    def send_status_update(self, client_id, status, message=None, download_url=None):
        """Send status update to FastAPI server"""
        try:
            payload = {
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
                "worker": socket.gethostname()
            }
            
            if message:
                payload["message"] = message
                
            if download_url:
                payload["download_url"] = download_url
                
            response = requests.post(
                f"{FASTAPI_URL}/status/{client_id}",
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Status update sent to client {client_id}: {status}")
        except Exception as e:
            logger.error(f"Failed to send status update: {str(e)}")
    
    def download_file(self, url, client_id):
        """Download a file using yt-dlp"""
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
        
        try:
            # Send download started status
            self.send_status_update(client_id, "downloading", "Download started")
            
            # Build yt-dlp command
            cmd = [
                'yt-dlp',
                '--no-playlist',
                '--format', 'best[height<=720]',  # Limit to 720p or lower
                '--output', output_template,
                '--print', 'after_move:filepath',
                '--no-progress',
                url
            ]
            
            logger.info(f"Executing command: {' '.join(cmd)}")
            
            # Execute yt-dlp
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode != 0:
                error_msg = f"Download failed: {result.stderr}"
                logger.error(error_msg)
                self.send_status_update(client_id, "error", error_msg)
                return None
                
            # Get the path of the downloaded file
            file_path = result.stdout.strip()
            if not file_path or not os.path.exists(file_path):
                error_msg = "Download completed but file not found"
                logger.error(error_msg)
                self.send_status_update(client_id, "error", error_msg)
                return None
                
            logger.info(f"Download completed: {file_path}")
            self.send_status_update(client_id, "processing", "Uploading to cloud storage")
            
            return file_path
            
        except subprocess.TimeoutExpired:
            error_msg = "Download timed out after 1 hour"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg)
            return None
        except Exception as e:
            error_msg = f"Download error: {str(e)}"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg)
            return None
        finally:
            # Clean up temp directory if file was moved
            if os.path.exists(temp_dir) and not os.path.exists(file_path):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def upload_to_gcs(self, file_path, client_id):
        """Upload file to Google Cloud Storage"""
        try:
            # Generate a unique filename
            filename = os.path.basename(file_path)
            unique_filename = f"{client_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
            
            # Upload to GCS
            blob = self.bucket.blob(unique_filename)
            blob.upload_from_filename(file_path)
            
            # Generate signed URL (valid for 24 hours)
            signed_url = blob.generate_signed_url(
                expiration=3600 * 24,  # 24 hours
                version="v4"
            )
            
            logger.info(f"File uploaded to GCS: {signed_url}")
            return signed_url
            
        except Exception as e:
            error_msg = f"Upload failed: {str(e)}"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg)
            return None
        finally:
            # Clean up downloaded file
            if os.path.exists(file_path):
                os.remove(file_path)
    
    def process_message(self, message):
        """Process a Pub/Sub message"""
        try:
            data = json.loads(message.data.decode('utf-8'))
            url = data.get('url')
            client_id = data.get('client_id')
            
            if not url or not client_id:
                logger.error("Invalid message: missing url or client_id")
                message.nack()  # Mark for retry
                return
            
            logger.info(f"Processing download request from {client_id}: {url}")
            
            # Download the file
            file_path = self.download_file(url, client_id)
            if not file_path:
                message.nack()  # Mark for retry
                return
            
            # Upload to GCS
            download_url = self.upload_to_gcs(file_path, client_id)
            if not download_url:
                message.nack()  # Mark for retry
                return
            
            # Send success status
            self.send_status_update(client_id, "completed", "Download completed", download_url)
            
            # Acknowledge the message
            message.ack()
            logger.info(f"Message processed successfully: {message.message_id}")
            
        except json.JSONDecodeError:
            logger.error("Invalid JSON in message")
            message.ack()  # Ack to avoid retrying invalid messages
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            message.nack()  # Mark for retry
    
    def run(self):
        """Start the worker"""
        logger.info("Starting yt-dlp worker")
        logger.info(f"Listening to subscription: {SUBSCRIPTION_NAME}")
        logger.info(f"Sending status updates to: {FASTAPI_URL}")
        
        # Define the message handler
        def callback(message):
            logger.info(f"Received message: {message.message_id}")
            self.process_message(message)
        
        # Start listening for messages
        streaming_pull_future = self.subscriber.subscribe(
            self.subscription_path, callback=callback
        )
        logger.info("Listening for messages...")
        
        try:
            # Block the main thread
            streaming_pull_future.result()
        except KeyboardInterrupt:
            streaming_pull_future.cancel()
            logger.info("Worker stopped by user")
        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            streaming_pull_future.cancel()

if __name__ == "__main__":
    worker = DownloadWorker()
    worker.run()