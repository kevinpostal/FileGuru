# worker.py
from dotenv import load_dotenv
import os

load_dotenv()
import json
import subprocess
import tempfile
import shutil
import logging
import re
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
        
    def send_status_update(self, client_id, status, message=None, download_url=None, file_name=None, url=None, progress=None, **kwargs):
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
                
            if progress is not None:
                payload["progress"] = progress
            
            # Add any additional kwargs
            payload.update(kwargs)
                
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

    def parse_progress_line(self, line, client_id, url):
        """Parse progress information from yt-dlp output"""
        try:
            # Look for download progress patterns
            if 'download:' in line and '%' in line:
                # Parse the custom progress template
                # Format: download:percent% of total_size at speed ETA eta
                
                # Extract percentage
                percent_match = re.search(r'(\d+(?:\.\d+)?)%', line)
                if percent_match:
                    progress = float(percent_match.group(1))
                    
                    # Extract speed if available
                    speed_match = re.search(r'at\s+([^\s]+)', line)
                    speed = speed_match.group(1) if speed_match else None
                    
                    # Extract ETA if available
                    eta_match = re.search(r'ETA\s+([^\s]+)', line)
                    eta = eta_match.group(1) if eta_match else None
                    
                    # Extract file size info (total size estimate)
                    size_match = re.search(r'of\s+([^\s]+)', line)
                    total_size = size_match.group(1) if size_match else None
                    
                    # Create progress message
                    message_parts = [f"Downloading... {progress:.1f}%"]
                    if speed and speed != 'N/A':
                        message_parts.append(f"at {speed}")
                    if eta and eta != 'N/A':
                        message_parts.append(f"ETA {eta}")
                    
                    message = " ".join(message_parts)
                    
                    # Send progress update with throttling
                    self.send_throttled_progress_update(client_id, progress, message, url, speed, eta, total_size)
            
            # Also look for other useful information and standard yt-dlp progress patterns
            elif '[download]' in line:
                if 'Destination:' in line:
                    # File destination info
                    logger.info(f"Download destination: {line}")
                elif 'has already been downloaded' in line:
                    # File already exists
                    self.send_status_update(client_id, "downloading", "File already exists, skipping download", url=url)
                elif '%' in line and ('ETA' in line or 'at' in line):
                    # Standard yt-dlp progress format: [download]  45.2% of 123.45MiB at 1.23MiB/s ETA 00:42
                    percent_match = re.search(r'(\d+(?:\.\d+)?)%', line)
                    if percent_match:
                        progress = float(percent_match.group(1))
                        
                        # Extract additional info from standard format
                        size_match = re.search(r'of\s+([^\s]+)', line)
                        speed_match = re.search(r'at\s+([^\s]+)', line)
                        eta_match = re.search(r'ETA\s+([^\s]+)', line)
                        
                        total_size = size_match.group(1) if size_match else None
                        speed = speed_match.group(1) if speed_match else None
                        eta = eta_match.group(1) if eta_match else None
                        
                        # Create progress message
                        message_parts = [f"Downloading... {progress:.1f}%"]
                        if speed and speed != 'N/A':
                            message_parts.append(f"at {speed}")
                        if eta and eta != 'N/A' and eta != '00:00':
                            message_parts.append(f"ETA {eta}")
                        
                        message = " ".join(message_parts)
                        
                        # Send progress update with throttling
                        self.send_throttled_progress_update(client_id, progress, message, url, speed, eta, total_size)
                
        except Exception as e:
            logger.error(f"Error parsing progress line '{line}': {str(e)}")

    def send_throttled_progress_update(self, client_id, progress, message, url, speed=None, eta=None, total_size=None):
        """Send progress update with throttling to avoid spam"""
        try:
            # Send update (but don't spam - only send every 2% or every 5 seconds)
            current_time = datetime.now()
            last_update_key = f"{client_id}_last_progress_update"
            last_progress_key = f"{client_id}_last_progress"
            
            if not hasattr(self, '_progress_cache'):
                self._progress_cache = {}
            
            last_update = self._progress_cache.get(last_update_key, datetime.min)
            last_progress = self._progress_cache.get(last_progress_key, 0)
            
            time_diff = (current_time - last_update).total_seconds()
            progress_diff = abs(progress - last_progress)
            
            # Send update if significant progress change, enough time passed, or near completion
            if progress_diff >= 2.0 or time_diff >= 5.0 or progress >= 99.0:
                payload = {
                    "status": "downloading",
                    "client_id": client_id,
                    "progress": progress,
                    "message": message,
                    "url": url,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "worker": socket.gethostname()
                }
                
                if speed and speed != 'N/A':
                    payload["download_speed"] = speed
                if eta and eta != 'N/A' and eta != '00:00':
                    payload["eta"] = eta
                if total_size:
                    payload["file_size"] = total_size
                
                try:
                    response = requests.post(
                        f"{FASTAPI_URL}/status/{client_id}",
                        json=payload,
                        timeout=5
                    )
                    response.raise_for_status()
                    
                    self._progress_cache[last_update_key] = current_time
                    self._progress_cache[last_progress_key] = progress
                    
                    logger.info(f"Progress update sent: {progress:.1f}% for client {client_id}")
                except Exception as e:
                    logger.error(f"Failed to send progress update: {str(e)}")
        except Exception as e:
            logger.error(f"Error in throttled progress update: {str(e)}")

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
                '--progress',
                '--progress-template', 'download:%(progress.percent)s%% of %(progress.total_bytes_estimate)s at %(progress.speed)s ETA %(progress.eta)s',
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
            
            # Execute yt-dlp with real-time progress monitoring
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor progress in real-time
            stdout_lines = []
            stderr_lines = []
            
            while True:
                # Check if process has finished
                if process.poll() is not None:
                    break
                
                # Read stderr for progress updates
                stderr_line = process.stderr.readline()
                if stderr_line:
                    stderr_line = stderr_line.strip()
                    stderr_lines.append(stderr_line)
                    self.parse_progress_line(stderr_line, client_id, url)
                
                # Read stdout for file path (this is where the final file path will be)
                stdout_line = process.stdout.readline()
                if stdout_line:
                    stdout_line = stdout_line.strip()
                    stdout_lines.append(stdout_line)
                    # Log stdout lines to help debug file path detection
                    if stdout_line and not stdout_line.startswith('['):
                        logger.info(f"Stdout line (potential file path): {stdout_line}")
            
            # Get any remaining output
            remaining_stdout, remaining_stderr = process.communicate()
            if remaining_stdout:
                for line in remaining_stdout.splitlines():
                    line = line.strip()
                    if line:
                        stdout_lines.append(line)
                        if not line.startswith('['):
                            logger.info(f"Remaining stdout line (potential file path): {line}")
            if remaining_stderr:
                for line in remaining_stderr.splitlines():
                    line = line.strip()
                    if line:
                        stderr_lines.append(line)
                        self.parse_progress_line(line, client_id, url)
            
            # Create result object similar to subprocess.run
            class ProcessResult:
                def __init__(self, returncode, stdout, stderr):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr
            
            result = ProcessResult(
                process.returncode,
                '\n'.join(stdout_lines),
                '\n'.join(stderr_lines)
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
                    
                    # Execute retry with progress monitoring
                    process_retry = subprocess.Popen(
                        cmd_retry,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True
                    )
                    
                    # Monitor retry progress
                    stdout_lines_retry = []
                    stderr_lines_retry = []
                    
                    while True:
                        if process_retry.poll() is not None:
                            break
                        
                        stderr_line = process_retry.stderr.readline()
                        if stderr_line:
                            stderr_lines_retry.append(stderr_line)
                            self.parse_progress_line(stderr_line.strip(), client_id, url)
                        
                        stdout_line = process_retry.stdout.readline()
                        if stdout_line:
                            stdout_lines_retry.append(stdout_line)
                    
                    # Get remaining output
                    remaining_stdout_retry, remaining_stderr_retry = process_retry.communicate()
                    if remaining_stdout_retry:
                        stdout_lines_retry.extend(remaining_stdout_retry.splitlines())
                    if remaining_stderr_retry:
                        stderr_lines_retry.extend(remaining_stderr_retry.splitlines())
                        for line in remaining_stderr_retry.splitlines():
                            self.parse_progress_line(line.strip(), client_id, url)
                    
                    result_retry = ProcessResult(
                        process_retry.returncode,
                        '\n'.join(stdout_lines_retry),
                        '\n'.join(stderr_lines_retry)
                    )
                    
                    if result_retry.returncode == 0:
                        # Success with retry - use same file detection logic
                        file_path = None
                        for line in reversed(stdout_lines_retry):
                            if line and not line.startswith('[') and os.path.exists(line):
                                file_path = line
                                break
                        
                        if not file_path:
                            potential_path = result_retry.stdout.strip()
                            if potential_path and os.path.exists(potential_path):
                                file_path = potential_path
                        
                        if not file_path:
                            for root, dirs, files in os.walk(temp_dir):
                                for file in files:
                                    if not file.startswith('.'):
                                        file_path = os.path.join(root, file)
                                        break
                                if file_path:
                                    break
                        
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
            # Look for the file path in stdout lines (should be the last non-empty line that's not a log message)
            file_path = None
            for line in reversed(stdout_lines):
                if line and not line.startswith('[') and os.path.exists(line):
                    file_path = line
                    break
            
            # Fallback: try the entire stdout as a single path
            if not file_path:
                potential_path = result.stdout.strip()
                if potential_path and os.path.exists(potential_path):
                    file_path = potential_path
            
            # Fallback: look for files in the temp directory
            if not file_path:
                logger.warning("File path not found in stdout, searching temp directory...")
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if not file.startswith('.'):  # Skip hidden files
                            file_path = os.path.join(root, file)
                            logger.info(f"Found file in temp directory: {file_path}")
                            break
                    if file_path:
                        break
            
            if not file_path or not os.path.exists(file_path):
                error_msg = f"Download completed but file not found. Stdout: {result.stdout[:200]}..."
                logger.error(error_msg)
                logger.error(f"Temp directory contents: {os.listdir(temp_dir) if os.path.exists(temp_dir) else 'N/A'}")
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