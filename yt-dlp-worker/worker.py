# worker.py
from dotenv import load_dotenv
import os

load_dotenv()
import json
import subprocess
import tempfile
import shutil
import logging
from datetime import datetime, timezone
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
PROJECT_ID = os.getenv('PROJECT_ID', 'hosting-shit')
SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION', 'yt-dlp-downloads-sub')
FASTAPI_URL = os.getenv('FASTAPI_URL', 'https://yt-dlp-server-578977081858.us-central1.run.app/')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'hosting-shit')
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/tmp/downloads')
COOKIES_FILE = os.getenv('COOKIES_FILE', 'cookies.txt')

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class DownloadWorker:
    def __init__(self):
        # Get credentials from environment variable
        credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        
        if credentials_path and os.path.exists(credentials_path):
            # Use service account credentials
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self.subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
            self.storage_client = storage.Client(credentials=credentials)
        else:
            # Use application default credentials (when running on Google Cloud)
            self.subscriber = pubsub_v1.SubscriberClient()
            self.storage_client = storage.Client()
        
        self.bucket = self.storage_client.bucket(GCS_BUCKET_NAME)
        self.subscription_path = self.subscriber.subscription_path(
            PROJECT_ID, SUBSCRIPTION_NAME
        )
        
    def send_status_update(self, client_id, status, message=None, download_url=None, file_name=None, url=None):
        """Send status update to FastAPI server"""
        try:
            payload = {
                "status": status,
                "client_id": client_id,  # Include client_id in the payload
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "worker": socket.gethostname()
            }
            
            if message:
                payload["message"] = message
                
            if download_url:
                payload["download_url"] = download_url
                
            if file_name:
                payload["file_name"] = file_name
                
            if url:
                payload["url"] = url
                
            response = requests.post(
                f"{FASTAPI_URL}/status/{client_id}",
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Status update sent to client {client_id}: {status}")
        except Exception as e:
            logger.error(f"Failed to send status update: {str(e)}")
    
    def get_format_for_platform(self, url):
        """Get appropriate format string based on the platform"""
        url_lower = url.lower()
        
        if 'instagram.com' in url_lower:
            # Instagram often has limited formats, be more flexible
            return 'best'
        elif 'tiktok.com' in url_lower:
            # TikTok usually has good format availability
            return 'best[height<=1080]/best'
        elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            # YouTube has extensive format options
            return 'best[height<=1080]/best[ext=mp4]/best'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            # Twitter/X has limited formats
            return 'best'
        else:
            # Default for other platforms
            return 'best[height<=1080]/best'

    def download_file(self, url, client_id):
        """Download a file using yt-dlp"""
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
        
        try:
            # Send download started status
            self.send_status_update(client_id, "downloading", "Download started", url=url)
            
            # Get platform-specific format
            format_selector = self.get_format_for_platform(url)
            
            # Build yt-dlp command with platform-appropriate format selection
            cmd = [
                'yt-dlp',
                '--no-playlist',
                '--format', format_selector,
                '--output', output_template,
                '--print', 'after_move:filepath',
                '--no-progress',
                url
            ]
            
            # Add cookies if available
            if os.path.exists(COOKIES_FILE):
                cmd.extend(['--cookies', COOKIES_FILE])
                logger.info(f"Using cookies file: {COOKIES_FILE}")
            else:
                logger.warning(f"Cookies file not found: {COOKIES_FILE}")
                # Try to use browser cookies as fallback
                cmd.extend(['--cookies-from-browser', 'chrome'])
                logger.info("Attempting to use cookies from Chrome browser")
            
            logger.info(f"Executing command: {' '.join(cmd)}")
            logger.info(f"Using format selector: {format_selector} for URL: {url}")
            
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
                
                # If format error, try with just 'best' format
                if "Requested format is not available" in result.stderr:
                    logger.info("Retrying with 'best' format...")
                    self.send_status_update(client_id, "downloading", "Retrying with different format...", url=url)
                    
                    # Retry with just 'best' format
                    cmd_retry = [
                        'yt-dlp',
                        '--no-playlist',
                        '--format', 'best',
                        '--output', output_template,
                        '--print', 'after_move:filepath',
                        '--no-progress',
                        url
                    ]
                    
                    # Add cookies to retry command too
                    if os.path.exists(COOKIES_FILE):
                        cmd_retry.extend(['--cookies', COOKIES_FILE])
                    else:
                        cmd_retry.extend(['--cookies-from-browser', 'chrome'])
                    
                    logger.info(f"Retry command: {' '.join(cmd_retry)}")
                    result_retry = subprocess.run(
                        cmd_retry,
                        capture_output=True,
                        text=True,
                        timeout=3600
                    )
                    
                    if result_retry.returncode == 0:
                        # Success with retry
                        file_path = result_retry.stdout.strip()
                        if file_path and os.path.exists(file_path):
                            logger.info(f"Download completed with retry: {file_path}")
                            self.send_status_update(client_id, "processing", "Uploading to cloud storage", url=url)
                            return file_path, temp_dir
                    
                    # If retry also failed, log both errors
                    logger.error(f"Retry also failed: {result_retry.stderr}")
                    error_msg = f"Download failed even with fallback format. Original error: {result.stderr}"
                
                self.send_status_update(client_id, "error", error_msg, url=url)
                return None, temp_dir
                
            # Get the path of the downloaded file
            file_path = result.stdout.strip()
            if not file_path or not os.path.exists(file_path):
                error_msg = "Download completed but file not found"
                logger.error(error_msg)
                self.send_status_update(client_id, "error", error_msg, url=url)
                return None, temp_dir
                
            logger.info(f"Download completed: {file_path}")
            self.send_status_update(client_id, "processing", "Uploading to cloud storage", url=url)
            
            return file_path, temp_dir
            
        except subprocess.TimeoutExpired:
            error_msg = "Download timed out after 1 hour"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg, url=url)
            return None, temp_dir
        except Exception as e:
            error_msg = f"Download error: {str(e)}"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg, url=url)
            return None, temp_dir
    
    def create_tinyurl(self, long_url):
        """Create a TinyURL short link for the given URL"""
        try:
            tinyurl_api = "http://tinyurl.com/api-create.php"
            response = requests.get(tinyurl_api, params={'url': long_url}, timeout=10)
            response.raise_for_status()
            
            short_url = response.text.strip()
            if short_url.startswith('http'):
                logger.info(f"Created TinyURL: {short_url}")
                return short_url
            else:
                logger.warning(f"TinyURL API returned unexpected response: {short_url}")
                return long_url
                
        except Exception as e:
            logger.error(f"Failed to create TinyURL: {str(e)}")
            return long_url  # Return original URL if shortening fails

    def upload_to_gcs(self, file_path, client_id, url=None):
        """Upload file to Google Cloud Storage"""
        try:
            # Generate a unique filename
            filename = os.path.basename(file_path)
            unique_filename = f"{client_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{filename}"
            
            # Upload to GCS
            blob = self.bucket.blob(unique_filename)
            blob.upload_from_filename(file_path)
            
            # Generate signed URL (valid for 24 hours)
            signed_url = blob.generate_signed_url(
                expiration=3600 * 24,  # 24 hours
                version="v4"
            )
            
            # Create TinyURL short link
            short_url = self.create_tinyurl(signed_url)
            
            logger.info(f"File uploaded to GCS: {signed_url}")
            logger.info(f"Short URL created: {short_url}")
            return short_url, unique_filename
            
        except Exception as e:
            error_msg = f"Upload failed: {str(e)}"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg, url=url)
            return None, None
    
    def process_message(self, message):
        """Process a Pub/Sub message"""
        temp_dir = None
        try:
            data = json.loads(message.data.decode('utf-8'))
            url = data.get('url')
            client_id = data.get('client_id')
            
            if not url or not client_id:
                logger.error("Invalid message: missing url or client_id")
                message.ack()  # Acknowledge invalid messages
                return
            
            logger.info(f"Processing download request from {client_id}: {url}")
            
            # Download the file
            file_path, temp_dir = self.download_file(url, client_id)
            if file_path:
                # Upload to GCS
                download_url, file_name = self.upload_to_gcs(file_path, client_id, url)
                if download_url:
                    # Send success status
                    self.send_status_update(
                        client_id,
                        "completed",
                        f"Download completed successfully",
                        download_url,
                        file_name,
                        url
                    )

        except json.JSONDecodeError:
            logger.error("Invalid JSON in message")
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
        finally:
            # Clean up temp directory
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Cleaned up temp directory: {temp_dir}")

            # Acknowledge the message
            message.ack()
            logger.info(f"Message processed: {message.message_id}")
    
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