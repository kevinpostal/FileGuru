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
from datetime import datetime, timezone, timedelta
from google.cloud import pubsub_v1, storage
from google.auth import credentials
import requests
from urllib.parse import urlparse
import socket
import unicodedata

# Configure logging with enhanced progress debugging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('yt-dlp-worker')

# Create a separate logger for progress parsing with more detailed output
progress_logger = logging.getLogger('yt-dlp-worker.progress')
progress_handler = logging.FileHandler('progress_debug.log')
progress_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
progress_logger.addHandler(progress_handler)
progress_logger.setLevel(logging.DEBUG)

# Configuration
PROJECT_ID = os.getenv('PROJECT_ID', 'hosting-shit')
SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION', 'yt-dlp-downloads-sub')
FASTAPI_URL = os.getenv('FASTAPI_URL', 'https://yt-dlp-server-578977081858.us-central1.run.app/')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'hosting-shit')
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/tmp/downloads')
COOKIES_FILE = os.getenv('COOKIES_FILE', 'cookies.txt')

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class FallbackProgressGenerator:
    """Generates realistic progress simulation with multi-phase progression"""
    
    def __init__(self, client_id, estimated_duration=None):
        self.client_id = client_id
        self.start_time = datetime.now()
        self.estimated_duration = estimated_duration or 300  # Default 5 minutes
        self.current_progress = 0.0
        self.current_phase = "initialization"
        self.last_update_time = self.start_time
        
        # Phase configuration
        self.phases = {
            "initialization": {
                "duration_ratio": 0.1,  # 10% of total time
                "progress_range": (0.0, 15.0),  # 0-15% progress
                "base_rate": 0.5,  # Base progress per second
                "variance": 0.3  # Rate variance factor
            },
            "downloading": {
                "duration_ratio": 0.75,  # 75% of total time
                "progress_range": (15.0, 85.0),  # 15-85% progress
                "base_rate": 0.8,  # Base progress per second
                "variance": 0.2  # Rate variance factor
            },
            "finalizing": {
                "duration_ratio": 0.15,  # 15% of total time
                "progress_range": (85.0, 95.0),  # 85-95% progress (never reach 100%)
                "base_rate": 0.2,  # Base progress per second
                "variance": 0.4  # Rate variance factor
            }
        }
        
        # Adaptive parameters
        self.download_patterns = {
            "small_file": {"duration": 60, "phases": {"initialization": 0.05, "downloading": 0.85, "finalizing": 0.1}},
            "medium_file": {"duration": 300, "phases": {"initialization": 0.1, "downloading": 0.75, "finalizing": 0.15}},
            "large_file": {"duration": 900, "phases": {"initialization": 0.15, "downloading": 0.7, "finalizing": 0.15}}
        }
        
        # Determine pattern based on estimated duration
        if self.estimated_duration <= 120:
            self.pattern = self.download_patterns["small_file"]
        elif self.estimated_duration <= 600:
            self.pattern = self.download_patterns["medium_file"]
        else:
            self.pattern = self.download_patterns["large_file"]
        
        # Update phase durations based on pattern
        for phase_name, phase_config in self.phases.items():
            if phase_name in self.pattern["phases"]:
                phase_config["duration_ratio"] = self.pattern["phases"][phase_name]
        
        logger.info(f"Initialized fallback progress generator for client {client_id} with pattern: {self.pattern}")
    
    def get_current_phase(self, elapsed_seconds):
        """Determine current phase based on elapsed time"""
        init_duration = self.estimated_duration * self.phases["initialization"]["duration_ratio"]
        download_duration = self.estimated_duration * self.phases["downloading"]["duration_ratio"]
        
        if elapsed_seconds <= init_duration:
            return "initialization"
        elif elapsed_seconds <= init_duration + download_duration:
            return "downloading"
        else:
            return "finalizing"
    
    def calculate_phase_progress(self, phase_name, elapsed_seconds, phase_elapsed):
        """Calculate progress within a specific phase"""
        phase_config = self.phases[phase_name]
        min_progress, max_progress = phase_config["progress_range"]
        
        # Calculate expected progress within phase
        phase_duration = self.estimated_duration * phase_config["duration_ratio"]
        if phase_duration <= 0:
            return min_progress
        
        # Base progress calculation
        phase_progress_ratio = min(1.0, phase_elapsed / phase_duration)
        
        # Apply non-linear progression for more realistic feel
        if phase_name == "initialization":
            # Slow start with exponential ramp-up
            adjusted_ratio = 1 - (1 - phase_progress_ratio) ** 2
        elif phase_name == "downloading":
            # Steady progress with slight deceleration
            adjusted_ratio = phase_progress_ratio ** 0.9
        else:  # finalizing
            # Significant slowdown near completion
            adjusted_ratio = phase_progress_ratio ** 1.5
        
        # Calculate target progress
        progress_range = max_progress - min_progress
        target_progress = min_progress + (progress_range * adjusted_ratio)
        
        return min(max_progress, target_progress)
    
    def add_realistic_variance(self, base_progress, phase_name):
        """Add realistic variance to progress updates"""
        import random
        
        phase_config = self.phases[phase_name]
        variance = phase_config["variance"]
        
        # Add small random variations
        variation = random.uniform(-variance, variance)
        adjusted_progress = base_progress + variation
        
        # Ensure progress doesn't go backwards significantly
        if adjusted_progress < self.current_progress - 0.5:
            adjusted_progress = self.current_progress - 0.1
        
        return adjusted_progress
    
    def update_progress(self):
        """Update and return current simulated progress"""
        current_time = datetime.now()
        elapsed_seconds = (current_time - self.start_time).total_seconds()
        
        # Determine current phase
        new_phase = self.get_current_phase(elapsed_seconds)
        if new_phase != self.current_phase:
            logger.info(f"Progress phase transition for client {self.client_id}: {self.current_phase} -> {new_phase}")
            self.current_phase = new_phase
        
        # Calculate phase-specific elapsed time
        init_duration = self.estimated_duration * self.phases["initialization"]["duration_ratio"]
        download_duration = self.estimated_duration * self.phases["downloading"]["duration_ratio"]
        
        if self.current_phase == "initialization":
            phase_elapsed = elapsed_seconds
        elif self.current_phase == "downloading":
            phase_elapsed = elapsed_seconds - init_duration
        else:  # finalizing
            phase_elapsed = elapsed_seconds - init_duration - download_duration
        
        # Calculate target progress for current phase
        target_progress = self.calculate_phase_progress(self.current_phase, elapsed_seconds, phase_elapsed)
        
        # Add realistic variance
        varied_progress = self.add_realistic_variance(target_progress, self.current_phase)
        
        # Smooth progress updates (don't jump too much)
        time_since_last_update = (current_time - self.last_update_time).total_seconds()
        max_increment = self.phases[self.current_phase]["base_rate"] * time_since_last_update * 2
        
        if varied_progress > self.current_progress + max_increment:
            varied_progress = self.current_progress + max_increment
        
        # Ensure progress is always forward (with small tolerance for variance)
        if varied_progress < self.current_progress - 0.1:
            varied_progress = self.current_progress
        
        # Never exceed 95% in simulation to avoid false completion
        self.current_progress = min(95.0, max(0.0, varied_progress))
        self.last_update_time = current_time
        
        return self.current_progress
    
    def get_progress_metadata(self):
        """Get metadata about current simulation state"""
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "progress_type": "simulated",
            "current_phase": self.current_phase,
            "elapsed_seconds": elapsed_seconds,
            "estimated_duration": self.estimated_duration,
            "pattern": self.pattern,
            "phase_config": self.phases[self.current_phase]
        }
    
    def adjust_duration_estimate(self, new_estimate):
        """Adjust estimated duration based on new information"""
        if new_estimate and new_estimate != self.estimated_duration:
            old_estimate = self.estimated_duration
            self.estimated_duration = new_estimate
            
            # Re-determine pattern if duration changed significantly
            if abs(new_estimate - old_estimate) > 60:  # More than 1 minute difference
                if self.estimated_duration <= 120:
                    self.pattern = self.download_patterns["small_file"]
                elif self.estimated_duration <= 600:
                    self.pattern = self.download_patterns["medium_file"]
                else:
                    self.pattern = self.download_patterns["large_file"]
                
                # Update phase durations
                for phase_name, phase_config in self.phases.items():
                    if phase_name in self.pattern["phases"]:
                        phase_config["duration_ratio"] = self.pattern["phases"][phase_name]
                
                logger.info(f"Adjusted duration estimate for client {self.client_id}: {old_estimate}s -> {new_estimate}s, new pattern: {self.pattern}")


class ProgressState:
    """Manages progress state for individual download clients"""
    
    def __init__(self, client_id):
        self.client_id = client_id
        self.real_progress = None
        self.simulated_progress = 0.0
        self.last_real_update = None
        self.fallback_active = False
        self.progress_history = []  # List of (timestamp, progress) tuples
        self.estimated_duration = None  # seconds
        self.download_start_time = datetime.now()
        self.current_phase = "initializing"  # "initializing", "downloading", "finalizing"
        self.last_progress_value = 0.0
        self.stall_detection_time = None
        self.progress_type = "real"  # "real", "simulated", "hybrid"
        
        # Progress smoothing parameters
        self.max_history_size = 10
        self.stall_timeout = 15.0  # seconds before considering progress stalled
        self.fallback_timeout = 5.0  # seconds before activating fallback
        
        # Initialize fallback progress generator
        self.fallback_generator = None
        
    def update_real_progress(self, progress, speed=None, eta=None, total_size=None):
        """Update with real progress data from yt-dlp"""
        current_time = datetime.now()
        
        # Validate progress
        if progress is None or progress < 0 or progress > 100:
            return False
            
        # Update real progress data
        self.real_progress = progress
        self.last_real_update = current_time
        self.progress_type = "real"
        
        # Add to history for validation and smoothing
        self.progress_history.append((current_time, progress))
        
        # Limit history size
        if len(self.progress_history) > self.max_history_size:
            self.progress_history.pop(0)
        
        # Update phase based on progress
        if progress < 5:
            self.current_phase = "initializing"
        elif progress < 95:
            self.current_phase = "downloading"
        else:
            self.current_phase = "finalizing"
        
        # Reset stall detection if progress increased
        if progress > self.last_progress_value:
            self.stall_detection_time = None
            self.last_progress_value = progress
        elif self.stall_detection_time is None:
            # Start stall detection timer
            self.stall_detection_time = current_time
        
        # Update estimated duration based on ETA if available
        if eta and self.estimated_duration is None:
            self.update_estimated_duration_from_eta(eta)
        
        # Deactivate fallback if we have real progress
        if self.fallback_active and progress > self.simulated_progress:
            self.fallback_active = False
            
        return True
    
    def update_estimated_duration_from_eta(self, eta_str):
        """Update estimated duration based on ETA string"""
        try:
            # Parse ETA string (format: HH:MM:SS or MM:SS)
            if ':' in eta_str:
                parts = eta_str.split(':')
                if len(parts) == 2:  # MM:SS
                    minutes, seconds = map(int, parts)
                    eta_seconds = minutes * 60 + seconds
                elif len(parts) == 3:  # HH:MM:SS
                    hours, minutes, seconds = map(int, parts)
                    eta_seconds = hours * 3600 + minutes * 60 + seconds
                else:
                    return
                
                # Estimate total duration based on current progress and ETA
                if self.real_progress and self.real_progress > 0:
                    remaining_progress = 100 - self.real_progress
                    if remaining_progress > 0:
                        # Calculate estimated total duration
                        progress_rate = self.real_progress / (datetime.now() - self.download_start_time).total_seconds()
                        if progress_rate > 0:
                            estimated_total = 100 / progress_rate
                            self.estimated_duration = int(estimated_total)
                            
                            # Update fallback generator if it exists
                            if self.fallback_generator:
                                self.fallback_generator.adjust_duration_estimate(self.estimated_duration)
                                
                            logger.info(f"Updated estimated duration for client {self.client_id}: {self.estimated_duration}s based on ETA: {eta_str}")
        except (ValueError, ZeroDivisionError) as e:
            logger.debug(f"Could not parse ETA '{eta_str}' for duration estimation: {str(e)}")
    
    def set_estimated_duration(self, duration_seconds):
        """Manually set estimated duration"""
        if duration_seconds and duration_seconds > 0:
            self.estimated_duration = duration_seconds
            
            # Update fallback generator if it exists
            if self.fallback_generator:
                self.fallback_generator.adjust_duration_estimate(duration_seconds)
                
            logger.info(f"Set estimated duration for client {self.client_id}: {duration_seconds}s")
    
    def get_current_progress(self):
        """Get the current progress value, handling fallback logic"""
        current_time = datetime.now()
        
        # Check if we should activate fallback
        if not self.fallback_active:
            if self.last_real_update is None:
                # No real progress yet, check timeout
                time_since_start = (current_time - self.download_start_time).total_seconds()
                if time_since_start > self.fallback_timeout:
                    self.activate_fallback()
            else:
                # Check for stalled progress
                time_since_update = (current_time - self.last_real_update).total_seconds()
                if time_since_update > self.stall_timeout:
                    self.activate_fallback()
        
        # Return appropriate progress value
        if self.fallback_active:
            return self.get_simulated_progress()
        elif self.real_progress is not None:
            return self.real_progress
        else:
            return self.get_simulated_progress()
    
    def activate_fallback(self):
        """Activate fallback progress simulation"""
        if not self.fallback_active:
            self.fallback_active = True
            self.progress_type = "simulated" if self.real_progress is None else "hybrid"
            
            # Initialize fallback progress generator
            if self.fallback_generator is None:
                self.fallback_generator = FallbackProgressGenerator(
                    self.client_id, 
                    self.estimated_duration
                )
                
                # If we have real progress, adjust the generator's starting point
                if self.real_progress is not None:
                    self.fallback_generator.current_progress = self.real_progress
                    
            logger.info(f"Activated fallback progress for client {self.client_id}")
    
    def get_simulated_progress(self):
        """Generate simulated progress using the fallback generator"""
        if self.fallback_generator is None:
            # Create fallback generator if not exists
            self.fallback_generator = FallbackProgressGenerator(
                self.client_id,
                self.estimated_duration
            )
        
        # Update and return simulated progress
        return self.fallback_generator.update_progress()
    
    def is_stalled(self):
        """Check if progress appears to be stalled"""
        if self.stall_detection_time is None:
            return False
            
        current_time = datetime.now()
        stall_duration = (current_time - self.stall_detection_time).total_seconds()
        return stall_duration > self.stall_timeout
    
    def get_progress_metadata(self):
        """Get metadata about current progress state"""
        metadata = {
            "progress_type": self.progress_type,
            "fallback_active": self.fallback_active,
            "current_phase": self.current_phase,
            "is_stalled": self.is_stalled(),
            "time_since_start": (datetime.now() - self.download_start_time).total_seconds(),
            "history_size": len(self.progress_history)
        }
        
        # Add fallback generator metadata if active
        if self.fallback_active and self.fallback_generator:
            fallback_metadata = self.fallback_generator.get_progress_metadata()
            metadata.update({
                "fallback_phase": fallback_metadata["current_phase"],
                "estimated_duration": fallback_metadata["estimated_duration"],
                "download_pattern": fallback_metadata["pattern"],
                "phase_config": fallback_metadata["phase_config"]
            })
        
        return metadata
    
    def validate_progress_consistency(self):
        """Validate progress consistency and detect anomalies"""
        if len(self.progress_history) < 2:
            return True
            
        # Check for backwards progress (should not happen)
        for i in range(1, len(self.progress_history)):
            prev_progress = self.progress_history[i-1][1]
            curr_progress = self.progress_history[i][1]
            
            if curr_progress < prev_progress - 1.0:  # Allow small decreases due to rounding
                logger.warning(f"Progress went backwards for client {self.client_id}: {prev_progress}% -> {curr_progress}%")
                return False
        
        return True
    
    def smooth_progress_updates(self):
        """Apply smoothing to progress updates to avoid jumps"""
        if len(self.progress_history) < 2:
            return self.real_progress
            
        # Get recent progress values
        recent_values = [entry[1] for entry in self.progress_history[-3:]]
        
        # Simple moving average for smoothing
        smoothed = sum(recent_values) / len(recent_values)
        
        # Don't smooth too aggressively - allow reasonable jumps
        if self.real_progress is not None:
            max_jump = 5.0  # Maximum allowed jump in percentage
            if abs(smoothed - self.real_progress) > max_jump:
                return self.real_progress
        
        return smoothed

def slugify(text, max_length=100):
    """
    Convert a string to a filesystem-safe slug.
    
    Args:
        text (str): The text to slugify
        max_length (int): Maximum length of the resulting slug
    
    Returns:
        str: A filesystem-safe slug
    """
    if not text:
        return "untitled"
    
    # Normalize unicode characters
    text = unicodedata.normalize('NFKD', text)
    
    # Remove or replace problematic characters
    # Replace common problematic characters with safe alternatives
    replacements = {
        '/': '-',
        '\\': '-',
        ':': '-',
        '*': '',
        '?': '',
        '"': '',
        '<': '',
        '>': '',
        '|': '-',
        '\n': ' ',
        '\r': ' ',
        '\t': ' '
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Remove any remaining non-ASCII characters that might cause issues
    text = text.encode('ascii', 'ignore').decode('ascii')
    
    # Replace multiple spaces/dashes with single ones
    text = re.sub(r'[-\s]+', '-', text)
    
    # Remove leading/trailing dashes and spaces
    text = text.strip('- ')
    
    # Truncate to max length while trying to preserve word boundaries
    if len(text) > max_length:
        text = text[:max_length]
        # Try to cut at a word boundary
        last_dash = text.rfind('-')
        if last_dash > max_length * 0.7:  # Only if we don't lose too much
            text = text[:last_dash]
    
    # Ensure we have something
    if not text:
        return "untitled"
    
    return text

class DownloadWorker:
    def __init__(self):
        # Initialize progress parsing statistics
        self._progress_stats = {
            'total_lines_processed': 0,
            'successful_parses': 0,
            'failed_parses': 0,
            'pattern_matches': {},
            'validation_failures': 0
        }
        
        # Progress state management
        self._progress_states = {}  # client_id -> ProgressState
        # Initialize Google Cloud clients with proper credential handling
        credentials = None
        credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        
        if credentials_path:
            # Check if the credentials file exists
            if os.path.exists(credentials_path):
                try:
                    # Use service account credentials
                    from google.oauth2 import service_account
                    credentials = service_account.Credentials.from_service_account_file(
                        credentials_path,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    logger.info(f"Using service account credentials from: {credentials_path}")
                except Exception as e:
                    logger.error(f"Failed to load service account credentials from {credentials_path}: {str(e)}")
                    logger.info("Falling back to default credentials")
                    credentials = None
            else:
                logger.warning(f"Service account key file not found at: {credentials_path}")
                logger.info("Falling back to default credentials (Application Default Credentials)")
        else:
            logger.info("No GOOGLE_APPLICATION_CREDENTIALS set, using default credentials")
        
        try:
            # Initialize clients with credentials (or None for default)
            if credentials:
                self.subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
                self.storage_client = storage.Client(credentials=credentials)
            else:
                # Use application default credentials (when running on Google Cloud or with gcloud auth)
                self.subscriber = pubsub_v1.SubscriberClient()
                self.storage_client = storage.Client()
                logger.info("Successfully initialized Google Cloud clients with default credentials")
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud clients: {str(e)}")
            raise
        
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

    def extract_video_metadata(self, url):
        """
        Extract video metadata (title, uploader, etc.) using yt-dlp
        
        Args:
            url (str): The video URL
            
        Returns:
            dict: Video metadata including title, uploader, duration, etc.
        """
        try:
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                url
            ]
            
            # Add cookies if available
            if os.path.exists(COOKIES_FILE):
                cmd.extend(['--cookies', COOKIES_FILE])
            else:
                cmd.extend(['--cookies-from-browser', 'chrome'])
            
            logger.info(f"Extracting metadata for: {url}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout for metadata extraction
            )
            
            if result.returncode == 0:
                metadata = json.loads(result.stdout)
                
                # Extract key information
                title = metadata.get('title', 'Untitled')
                uploader = metadata.get('uploader', metadata.get('channel', ''))
                duration = metadata.get('duration', 0)
                upload_date = metadata.get('upload_date', '')
                
                logger.info(f"Extracted metadata - Title: {title}, Uploader: {uploader}")
                
                return {
                    'title': title,
                    'uploader': uploader,
                    'duration': duration,
                    'upload_date': upload_date,
                    'original_url': url,
                    'full_metadata': metadata
                }
            else:
                logger.warning(f"Failed to extract metadata: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Metadata extraction timed out for: {url}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse metadata JSON: {str(e)}")
            return None
        except Exception as e:
            logger.warning(f"Error extracting metadata: {str(e)}")
            return None

    def parse_progress_line(self, line, client_id, url):
        """Parse progress information from yt-dlp output with enhanced pattern matching and robust error handling"""
        try:
            # Track statistics
            self._progress_stats['total_lines_processed'] += 1
            # Enhanced regex patterns for multiple yt-dlp output formats
            progress_patterns = [
                # Standard format: [download]  45.2% of 125.3MiB at 2.1MiB/s ETA 00:38
                r'\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+([^\s]+)\s+at\s+([^\s]+)\s+ETA\s+([^\s]+)',
                # Completion format: [download] 100% of 125.3MiB in 01:02
                r'\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+([^\s]+)\s+in\s+([^\s]+)',
                # Progress with speed but no ETA: 45.2% at 2.1MiB/s
                r'(\d+(?:\.\d+)?)%.*?at\s+([^\s]+)',
                # Progress with ETA but no speed: 45.2% ETA 00:38
                r'(\d+(?:\.\d+)?)%.*?ETA\s+([^\s]+)',
                # Simple percentage only: 45.2%
                r'(\d+(?:\.\d+)?)%',
                # Alternative format with "of" but different structure
                r'(\d+(?:\.\d+)?)%.*?of\s+([^\s]+)',
                # Format with file size in different position
                r'(\d+(?:\.\d+)?)%.*?([^\s]+/s).*?([^\s]+)',
            ]
            
            # Check if line contains progress indicators
            # Accept lines with percentage and common progress keywords, or yt-dlp download tags
            has_progress_indicators = (
                '%' in line and (
                    'download' in line.lower() or 
                    'eta' in line.lower() or 
                    'at' in line.lower() or
                    'remaining' in line.lower()
                )
            ) or '[download]' in line.lower()
            
            if not has_progress_indicators:
                progress_logger.debug(f"Line skipped (no progress indicators): {line}")
                return
            
            progress_logger.debug(f"Parsing progress line for client {client_id}: {line}")
            
            progress = None
            speed = None
            eta = None
            total_size = None
            
            # Try each pattern until one matches
            for i, pattern in enumerate(progress_patterns):
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    progress_logger.debug(f"Pattern {i+1} matched: {pattern}")
                    # Track pattern usage statistics
                    pattern_key = f"pattern_{i+1}"
                    self._progress_stats['pattern_matches'][pattern_key] = self._progress_stats['pattern_matches'].get(pattern_key, 0) + 1
                    groups = match.groups()
                    
                    # Extract progress percentage (always first group)
                    if groups[0]:
                        raw_progress = float(groups[0])
                        progress = self._validate_progress(raw_progress, client_id)
                    
                    # Extract additional data based on pattern
                    if len(groups) >= 2:
                        # Check if second group looks like speed (prioritize speed over size)
                        if groups[1] and '/s' in groups[1]:
                            speed = self._sanitize_speed(groups[1])
                        # Check if second group looks like file size
                        elif groups[1] and ('iB' in groups[1] or 'B' in groups[1] or 'bytes' in groups[1]) and '/s' not in groups[1]:
                            total_size = self._sanitize_size(groups[1])
                        # Check if second group looks like time (for completion format)
                        elif groups[1] and ':' in groups[1]:
                            eta = self._sanitize_eta(groups[1])
                    
                    if len(groups) >= 3:
                        # Third group could be speed or ETA
                        if groups[2] and '/s' in groups[2]:
                            speed = self._sanitize_speed(groups[2])
                        elif groups[2] and ':' in groups[2]:
                            eta = self._sanitize_eta(groups[2])
                    
                    if len(groups) >= 4:
                        # Fourth group is typically ETA
                        if groups[3] and ':' in groups[3]:
                            eta = self._sanitize_eta(groups[3])
                    
                    break
            
            # If no pattern matched but we have a percentage, try simple extraction
            if progress is None:
                percent_match = re.search(r'(\d+(?:\.\d+)?)%', line)
                if percent_match:
                    raw_progress = float(percent_match.group(1))
                    progress = self._validate_progress(raw_progress, client_id)
                    progress_logger.debug(f"Fallback percentage extraction: {progress}%")
            
            # Extract additional information with separate patterns if not found
            if progress is not None:
                if speed is None:
                    speed_match = re.search(r'at\s+([^\s]+/s)', line, re.IGNORECASE)
                    if speed_match:
                        speed = self._sanitize_speed(speed_match.group(1))
                
                if eta is None:
                    eta_match = re.search(r'ETA\s+([^\s]+)', line, re.IGNORECASE)
                    if eta_match:
                        eta = self._sanitize_eta(eta_match.group(1))
                
                if total_size is None:
                    size_match = re.search(r'of\s+([^\s]+)', line, re.IGNORECASE)
                    if size_match:
                        total_size = self._sanitize_size(size_match.group(1))
                
                # Create progress message
                message_parts = [f"Downloading... {progress:.1f}%"]
                if speed and speed != 'N/A':
                    message_parts.append(f"at {speed}")
                if eta and eta != 'N/A' and eta != '00:00':
                    message_parts.append(f"ETA {eta}")
                
                message = " ".join(message_parts)
                
                logger.info(f"Progress parsed for client {client_id}: {progress:.1f}% (speed: {speed}, ETA: {eta}, size: {total_size})")
                
                # Track successful parse
                self._progress_stats['successful_parses'] += 1
                
                # Reset parsing failure count on successful parse
                self._reset_parsing_failure_count(client_id)
                
                # Use progress state management for coordination
                managed_progress, metadata = self.manage_progress_coordination(client_id, progress, speed, eta, total_size)
                
                # Update message with managed progress
                message_parts = [f"Downloading... {managed_progress:.1f}%"]
                if speed and speed != 'N/A':
                    message_parts.append(f"at {speed}")
                if eta and eta != 'N/A' and eta != '00:00':
                    message_parts.append(f"ETA {eta}")
                
                managed_message = " ".join(message_parts)
                
                # Send progress update with throttling and metadata
                self.send_throttled_progress_update(client_id, managed_progress, managed_message, url, speed, eta, total_size, metadata)
            else:
                progress_logger.debug(f"No progress percentage found in line: {line}")
                # Track failed parse
                self._progress_stats['failed_parses'] += 1
                
        except ValueError as e:
            logger.warning(f"Invalid progress value in line '{line}': {str(e)}")
            self._progress_stats['failed_parses'] += 1
            self._handle_progress_parsing_failure(client_id, line, "ValueError", str(e))
        except Exception as e:
            logger.error(f"Error parsing progress line '{line}': {str(e)}")
            self._progress_stats['failed_parses'] += 1
            self._handle_progress_parsing_failure(client_id, line, "Exception", str(e))
    
    def _handle_progress_parsing_failure(self, client_id, line, error_type, error_message):
        """Handle progress parsing failures with recovery mechanisms"""
        try:
            # Get or create progress state for this client
            progress_state = self.get_or_create_progress_state(client_id)
            
            # Log detailed error information for debugging
            progress_logger.error(f"Progress parsing failure for client {client_id}: {error_type} - {error_message}")
            progress_logger.error(f"Failed line: '{line}'")
            
            # Increment failure counter for this client
            if not hasattr(self, '_parsing_failure_counts'):
                self._parsing_failure_counts = {}
            
            failure_key = f"{client_id}_parsing_failures"
            current_failures = self._parsing_failure_counts.get(failure_key, 0)
            self._parsing_failure_counts[failure_key] = current_failures + 1
            
            # If we have too many parsing failures, activate fallback progress
            if current_failures >= 3:  # After 3 consecutive failures
                logger.warning(f"Multiple progress parsing failures for client {client_id}, activating fallback progress")
                progress_state.activate_fallback()
                
                # Send a progress update with fallback to maintain user feedback
                current_progress = progress_state.get_current_progress()
                metadata = progress_state.get_progress_metadata()
                
                self.send_throttled_progress_update(
                    client_id, 
                    current_progress, 
                    f"Downloading... {current_progress:.1f}% (estimated)", 
                    "", 
                    metadata=metadata
                )
            
            # Reset failure counter on successful parse (handled elsewhere)
            
        except Exception as e:
            logger.error(f"Error in progress parsing failure handler: {str(e)}")
    
    def _reset_parsing_failure_count(self, client_id):
        """Reset parsing failure count on successful parse"""
        if hasattr(self, '_parsing_failure_counts'):
            failure_key = f"{client_id}_parsing_failures"
            if failure_key in self._parsing_failure_counts:
                self._parsing_failure_counts[failure_key] = 0

    def _validate_progress(self, progress, client_id):
        """Validate and sanitize progress percentage"""
        try:
            # Clamp progress to valid range (0-100)
            if progress < 0:
                logger.warning(f"Negative progress {progress}% for client {client_id}, clamping to 0%")
                return 0.0
            elif progress > 100:
                logger.warning(f"Progress {progress}% exceeds 100% for client {client_id}, clamping to 100%")
                return 100.0
            
            # Round to 1 decimal place for consistency
            return round(progress, 1)
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid progress value {progress} for client {client_id}: {str(e)}")
            self._progress_stats['validation_failures'] += 1
            return None
    
    def _sanitize_speed(self, speed_str):
        """Sanitize and validate download speed string"""
        try:
            if not speed_str or speed_str.lower() in ['n/a', 'unknown', '--']:
                return None
            
            # Remove extra whitespace and ensure it looks like a speed
            speed = speed_str.strip()
            if '/s' not in speed.lower():
                return None
            
            # Basic validation - should contain numbers and units
            if not re.search(r'\d', speed):
                return None
            
            return speed
        except Exception as e:
            progress_logger.debug(f"Error sanitizing speed '{speed_str}': {str(e)}")
            return None
    
    def _sanitize_eta(self, eta_str):
        """Sanitize and validate ETA string"""
        try:
            if not eta_str or eta_str.lower() in ['n/a', 'unknown', '--']:
                return None
            
            # Remove extra whitespace
            eta = eta_str.strip()
            
            # Should look like time format (HH:MM:SS or MM:SS)
            if not re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', eta):
                return None
            
            # Don't return 00:00 as it's not meaningful
            if eta in ['00:00', '0:00']:
                return None
            
            return eta
        except Exception as e:
            progress_logger.debug(f"Error sanitizing ETA '{eta_str}': {str(e)}")
            return None
    
    def _sanitize_size(self, size_str):
        """Sanitize and validate file size string"""
        try:
            if not size_str or size_str.lower() in ['n/a', 'unknown', '--']:
                return None
            
            # Remove extra whitespace
            size = size_str.strip()
            
            # Should contain numbers and size units
            if not re.search(r'\d', size):
                return None
            
            # Should contain size units (B, KB, MB, GB, etc.)
            if not re.search(r'[KMGT]?i?B', size, re.IGNORECASE):
                return None
            
            return size
        except Exception as e:
            progress_logger.debug(f"Error sanitizing size '{size_str}': {str(e)}")
            return None
    
    def log_progress_statistics(self, client_id=None):
        """Log comprehensive progress parsing statistics"""
        stats = self._progress_stats
        
        if stats['total_lines_processed'] == 0:
            return
        
        success_rate = (stats['successful_parses'] / stats['total_lines_processed']) * 100
        
        log_msg = [
            f"Progress parsing statistics{' for client ' + client_id if client_id else ''}:",
            f"  Total lines processed: {stats['total_lines_processed']}",
            f"  Successful parses: {stats['successful_parses']}",
            f"  Failed parses: {stats['failed_parses']}",
            f"  Validation failures: {stats['validation_failures']}",
            f"  Success rate: {success_rate:.1f}%"
        ]
        
        if stats['pattern_matches']:
            log_msg.append("  Pattern usage:")
            for pattern, count in stats['pattern_matches'].items():
                percentage = (count / stats['successful_parses']) * 100 if stats['successful_parses'] > 0 else 0
                log_msg.append(f"    {pattern}: {count} times ({percentage:.1f}%)")
        
        logger.info("\n".join(log_msg))
        progress_logger.info("\n".join(log_msg))
        
        # Also log error handling statistics
        self.log_error_handling_statistics(client_id)
    
    def log_error_handling_statistics(self, client_id=None):
        """Log comprehensive error handling and recovery statistics"""
        log_msg = [f"Error handling statistics{' for client ' + client_id if client_id else ''}:"]
        
        # Progress parsing failure statistics
        if hasattr(self, '_parsing_failure_counts'):
            if client_id:
                failure_key = f"{client_id}_parsing_failures"
                parsing_failures = self._parsing_failure_counts.get(failure_key, 0)
                log_msg.append(f"  Progress parsing failures: {parsing_failures}")
            else:
                total_parsing_failures = sum(self._parsing_failure_counts.values())
                log_msg.append(f"  Total progress parsing failures: {total_parsing_failures}")
        
        # WebSocket failure statistics
        if hasattr(self, '_websocket_failure_tracking'):
            if client_id:
                client_key = f"{client_id}_websocket_failures"
                ws_info = self._websocket_failure_tracking.get(client_key, {})
                log_msg.extend([
                    f"  WebSocket consecutive failures: {ws_info.get('consecutive_failures', 0)}",
                    f"  WebSocket total failures: {ws_info.get('total_failures', 0)}",
                    f"  WebSocket degraded mode: {ws_info.get('degraded_mode', False)}",
                    f"  WebSocket circuit breaker: {'active' if ws_info.get('circuit_breaker_until') and datetime.now() < ws_info.get('circuit_breaker_until') else 'inactive'}"
                ])
            else:
                total_ws_failures = sum(info.get('total_failures', 0) for info in self._websocket_failure_tracking.values())
                degraded_clients = sum(1 for info in self._websocket_failure_tracking.values() if info.get('degraded_mode', False))
                log_msg.extend([
                    f"  Total WebSocket failures: {total_ws_failures}",
                    f"  Clients in degraded mode: {degraded_clients}"
                ])
        
        # Stall detection statistics
        if hasattr(self, '_stall_detection'):
            if client_id:
                stall_key = f"{client_id}_stall_detection"
                stall_info = self._stall_detection.get(stall_key, {})
                log_msg.extend([
                    f"  Stall warnings: {stall_info.get('stall_warnings', 0)}",
                    f"  Recovery attempts: {stall_info.get('recovery_attempts', 0)}"
                ])
            else:
                total_stall_warnings = sum(info.get('stall_warnings', 0) for info in self._stall_detection.values())
                total_recovery_attempts = sum(info.get('recovery_attempts', 0) for info in self._stall_detection.values())
                log_msg.extend([
                    f"  Total stall warnings: {total_stall_warnings}",
                    f"  Total recovery attempts: {total_recovery_attempts}"
                ])
        
        if len(log_msg) > 1:  # Only log if there are actual statistics
            logger.info("\n".join(log_msg))
    
    def get_or_create_progress_state(self, client_id):
        """Get or create progress state for a client"""
        if client_id not in self._progress_states:
            self._progress_states[client_id] = ProgressState(client_id)
            logger.info(f"Created new progress state for client {client_id}")
        return self._progress_states[client_id]
    
    def cleanup_progress_state(self, client_id):
        """Clean up progress state and all error handling tracking for a completed download"""
        if client_id in self._progress_states:
            del self._progress_states[client_id]
            logger.info(f"Cleaned up progress state for client {client_id}")
        
        # Clean up all error handling tracking
        self._reset_stall_detection(client_id)
        self._reset_websocket_failure_tracking(client_id)
        self._reset_parsing_failure_count(client_id)
        
        # Clean up progress cache
        if hasattr(self, '_progress_cache'):
            keys_to_remove = [key for key in self._progress_cache.keys() if key.startswith(f"{client_id}_")]
            for key in keys_to_remove:
                del self._progress_cache[key]
        
        # Clean up connection quality cache
        if hasattr(self, '_connection_quality_cache'):
            keys_to_remove = [key for key in self._connection_quality_cache.keys() if key.startswith(f"{client_id}_")]
            for key in keys_to_remove:
                del self._connection_quality_cache[key]
        
        logger.info(f"Completed comprehensive cleanup for client {client_id}")
    
    def _estimate_download_duration(self, url):
        """Estimate download duration based on URL patterns and platform characteristics"""
        url_lower = url.lower()
        
        # Platform-based duration estimates (in seconds)
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            # YouTube videos vary widely, default to medium duration
            return 300  # 5 minutes
        elif 'instagram.com' in url_lower:
            # Instagram posts are usually shorter
            return 120  # 2 minutes
        elif 'tiktok.com' in url_lower:
            # TikTok videos are typically short
            return 90   # 1.5 minutes
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            # Twitter videos are usually short
            return 60   # 1 minute
        else:
            # Default for unknown platforms
            return 240  # 4 minutes
    
    def _start_progress_monitoring(self, client_id, url):
        """Start progress monitoring with fallback activation logic"""
        progress_state = self.get_or_create_progress_state(client_id)
        
        # Send initial progress update to establish baseline
        current_progress, metadata = self.manage_progress_coordination(client_id, None)
        
        # Create initial message
        initial_message = "Initializing download..."
        
        # Send initial update
        self.send_throttled_progress_update(
            client_id, current_progress, initial_message, url, 
            metadata=metadata
        )
        
        logger.info(f"Started progress monitoring for client {client_id} with estimated duration: {progress_state.estimated_duration}s")
    
    def _ensure_progress_continuity(self, client_id):
        """Ensure progress continuity and handle transitions between real and simulated progress"""
        progress_state = self.get_or_create_progress_state(client_id)
        current_time = datetime.now()
        
        # Check if we need to activate fallback due to timeout
        if not progress_state.fallback_active:
            if progress_state.last_real_update is None:
                # No real progress yet, check if we should activate fallback
                time_since_start = (current_time - progress_state.download_start_time).total_seconds()
                if time_since_start > progress_state.fallback_timeout:
                    logger.info(f"Activating fallback progress for client {client_id} - no real progress after {time_since_start:.1f}s")
                    progress_state.activate_fallback()
            else:
                # Check for stalled progress
                time_since_update = (current_time - progress_state.last_real_update).total_seconds()
                if time_since_update > progress_state.stall_timeout:
                    logger.info(f"Activating fallback progress for client {client_id} - progress stalled for {time_since_update:.1f}s")
                    progress_state.activate_fallback()
        
        # Handle transition back to real progress if it becomes available
        elif progress_state.fallback_active and progress_state.real_progress is not None:
            # Check if real progress has resumed and is ahead of simulated
            if progress_state.real_progress > progress_state.get_simulated_progress():
                logger.info(f"Transitioning back to real progress for client {client_id} - real: {progress_state.real_progress}%, simulated: {progress_state.get_simulated_progress()}%")
                progress_state.fallback_active = False
                progress_state.progress_type = "real"
        
        return progress_state.get_current_progress(), progress_state.get_progress_metadata()
    
    def manage_progress_coordination(self, client_id, progress, speed=None, eta=None, total_size=None):
        """Coordinate between real and simulated progress with seamless transitions"""
        progress_state = self.get_or_create_progress_state(client_id)
        
        # Update with real progress data if provided
        if progress is not None:
            success = progress_state.update_real_progress(progress, speed, eta, total_size)
            if not success:
                logger.warning(f"Failed to update real progress for client {client_id}")
        
        # Ensure progress continuity and handle transitions
        current_progress, metadata = self._ensure_progress_continuity(client_id)
        
        # Validate consistency
        if not progress_state.validate_progress_consistency():
            logger.warning(f"Progress consistency validation failed for client {client_id}")
        
        # Apply smoothing if needed
        if progress_state.real_progress is not None and not progress_state.fallback_active:
            smoothed_progress = progress_state.smooth_progress_updates()
            if smoothed_progress != progress_state.real_progress:
                logger.debug(f"Applied progress smoothing for client {client_id}: {progress_state.real_progress}% -> {smoothed_progress}%")
                current_progress = smoothed_progress
        
        return current_progress, metadata

    def send_throttled_progress_update(self, client_id, progress, message, url, speed=None, eta=None, total_size=None, metadata=None):
        """Send progress update with adaptive throttling and rich metadata"""
        try:
            current_time = datetime.now()
            
            # Initialize caches if not exists
            if not hasattr(self, '_progress_cache'):
                self._progress_cache = {}
            if not hasattr(self, '_connection_quality_cache'):
                self._connection_quality_cache = {}
            if not hasattr(self, '_throttling_config'):
                self._throttling_config = {}
            
            # Cache keys for this client
            last_update_key = f"{client_id}_last_progress_update"
            last_progress_key = f"{client_id}_last_progress"
            update_count_key = f"{client_id}_update_count"
            failed_requests_key = f"{client_id}_failed_requests"
            response_times_key = f"{client_id}_response_times"
            
            # Get cached values
            last_update = self._progress_cache.get(last_update_key, datetime.min)
            last_progress = self._progress_cache.get(last_progress_key, 0)
            update_count = self._progress_cache.get(update_count_key, 0)
            failed_requests = self._connection_quality_cache.get(failed_requests_key, 0)
            response_times = self._connection_quality_cache.get(response_times_key, [])
            
            # Calculate progress metrics
            time_diff = (current_time - last_update).total_seconds()
            progress_diff = abs(progress - last_progress)
            
            # Determine progress rate (percentage per second)
            progress_rate = progress_diff / max(time_diff, 0.1) if time_diff > 0 else 0
            
            # Calculate connection quality metrics
            avg_response_time = sum(response_times[-10:]) / len(response_times[-10:]) if response_times else 0.5
            connection_quality = self._assess_connection_quality(failed_requests, avg_response_time, update_count)
            
            # Check if WebSocket is in degraded mode
            is_degraded = self._is_websocket_degraded(client_id)
            
            # Adaptive throttling based on progress rate, connection quality, and degraded mode
            throttling_config = self._get_adaptive_throttling_config(
                progress_rate, connection_quality, metadata, is_degraded
            )
            
            min_progress_diff = throttling_config["min_progress_diff"]
            min_time_diff = throttling_config["min_time_diff"]
            max_time_diff = throttling_config["max_time_diff"]
            
            # Determine if update should be sent
            should_send_update = (
                progress_diff >= min_progress_diff or  # Significant progress change
                time_diff >= max_time_diff or         # Maximum time elapsed (ensure regular updates)
                (time_diff >= min_time_diff and progress_rate > 0.1) or  # Minimum time with active progress
                progress >= 99.0 or                   # Near completion
                progress <= 1.0 or                    # Just started
                (metadata and metadata.get("progress_type") != "real")  # Always send simulated/hybrid updates more frequently
            )
            
            if should_send_update:
                # Build enhanced payload with rich metadata
                payload = self._build_enhanced_progress_payload(
                    client_id, progress, message, url, speed, eta, total_size, metadata, throttling_config
                )
                
                # Send update with connection quality tracking
                request_start_time = datetime.now()
                success = self._send_progress_request(client_id, payload, request_start_time)
                
                if success:
                    # Update caches on successful send
                    self._progress_cache[last_update_key] = current_time
                    self._progress_cache[last_progress_key] = progress
                    self._progress_cache[update_count_key] = update_count + 1
                    
                    # Track response time for connection quality assessment
                    response_time = (datetime.now() - request_start_time).total_seconds()
                    response_times.append(response_time)
                    if len(response_times) > 20:  # Keep only recent response times
                        response_times.pop(0)
                    self._connection_quality_cache[response_times_key] = response_times
                    
                    # Reset failed requests counter on success
                    self._connection_quality_cache[failed_requests_key] = max(0, failed_requests - 1)
                    
                    progress_type = metadata.get("progress_type", "real") if metadata else "real"
                    logger.info(f"Progress update sent: {progress:.1f}% ({progress_type}) for client {client_id} "
                              f"[rate: {progress_rate:.2f}%/s, quality: {connection_quality}, throttle: {min_time_diff:.1f}s]")
                else:
                    # Track failed request for connection quality assessment
                    self._connection_quality_cache[failed_requests_key] = failed_requests + 1
                    
        except Exception as e:
            logger.error(f"Error in adaptive throttled progress update: {str(e)}")
    
    def _assess_connection_quality(self, failed_requests, avg_response_time, update_count):
        """Assess connection quality based on failure rate and response times"""
        if update_count == 0:
            return "good"  # Default for new connections
        
        failure_rate = failed_requests / max(update_count, 1)
        
        # Classify connection quality
        if failure_rate > 0.3 or avg_response_time > 2.0:
            return "poor"
        elif failure_rate > 0.1 or avg_response_time > 1.0:
            return "fair"
        else:
            return "good"
    
    def _get_adaptive_throttling_config(self, progress_rate, connection_quality, metadata, is_degraded=False):
        """Get adaptive throttling configuration based on progress rate, connection quality, and degraded mode"""
        # Base configuration
        config = {
            "min_progress_diff": 2.0,  # Default minimum progress difference
            "min_time_diff": 2.0,      # Default minimum time difference
            "max_time_diff": 5.0,      # Default maximum time difference
        }
        
        # Adjust based on progress rate
        if progress_rate > 5.0:  # Fast progress
            config["min_progress_diff"] = 1.0  # More frequent updates
            config["min_time_diff"] = 1.0
        elif progress_rate > 2.0:  # Moderate progress
            config["min_progress_diff"] = 1.5
            config["min_time_diff"] = 1.5
        elif progress_rate < 0.1:  # Very slow progress
            config["min_progress_diff"] = 0.5  # Send updates even for small changes
            config["min_time_diff"] = 3.0     # But not too frequently
        
        # Adjust based on connection quality
        if connection_quality == "poor":
            # Reduce update frequency for poor connections
            config["min_time_diff"] = max(config["min_time_diff"] * 1.5, 3.0)
            config["max_time_diff"] = min(config["max_time_diff"] * 1.5, 10.0)
        elif connection_quality == "good":
            # Allow more frequent updates for good connections
            config["min_time_diff"] = max(config["min_time_diff"] * 0.8, 1.0)
        
        # Adjust for degraded WebSocket mode
        if is_degraded:
            # Significantly reduce update frequency in degraded mode to avoid overwhelming failing connection
            config["min_time_diff"] = max(config["min_time_diff"] * 2.0, 5.0)
            config["max_time_diff"] = min(config["max_time_diff"] * 2.0, 15.0)
            config["min_progress_diff"] = max(config["min_progress_diff"] * 1.5, 5.0)
            logger.debug(f"Throttling adjusted for degraded WebSocket mode: {config}")
        
        # Adjust based on progress type
        if metadata:
            progress_type = metadata.get("progress_type", "real")
            if progress_type in ["simulated", "hybrid"]:
                # More frequent updates for simulated progress to maintain smooth UX
                config["min_time_diff"] = max(config["min_time_diff"] * 0.7, 1.0)
                config["min_progress_diff"] = max(config["min_progress_diff"] * 0.7, 0.5)
            
            # More frequent updates if progress is stalled
            if metadata.get("is_stalled", False):
                config["min_time_diff"] = max(config["min_time_diff"] * 0.5, 1.0)
        
        return config
    
    def _detect_download_stall(self, client_id, process):
        """Detect if download process appears to be stalled"""
        try:
            progress_state = self.get_or_create_progress_state(client_id)
            
            # Initialize stall detection tracking if not exists
            if not hasattr(self, '_stall_detection'):
                self._stall_detection = {}
            
            stall_key = f"{client_id}_stall_detection"
            stall_info = self._stall_detection.get(stall_key, {
                'last_progress_change': datetime.now(),
                'last_progress_value': 0.0,
                'stall_warnings': 0,
                'recovery_attempts': 0,
                'process_start_time': datetime.now()
            })
            
            current_time = datetime.now()
            current_progress = progress_state.real_progress or 0.0
            
            # Check if progress has changed
            if current_progress > stall_info['last_progress_value'] + 0.1:  # Progress increased by at least 0.1%
                # Progress is moving, reset stall detection
                stall_info['last_progress_change'] = current_time
                stall_info['last_progress_value'] = current_progress
                stall_info['stall_warnings'] = 0
                self._stall_detection[stall_key] = stall_info
                return False, "active"
            
            # Calculate time since last progress change
            time_since_progress = (current_time - stall_info['last_progress_change']).total_seconds()
            time_since_start = (current_time - stall_info['process_start_time']).total_seconds()
            
            # Define stall thresholds based on download phase
            if current_progress < 5.0:
                # Initialization phase - allow more time
                stall_threshold = 30.0
            elif current_progress > 95.0:
                # Finalization phase - allow more time
                stall_threshold = 45.0
            else:
                # Active download phase
                stall_threshold = 20.0
            
            # Check for stall conditions
            is_stalled = False
            stall_reason = "active"
            
            if time_since_progress > stall_threshold:
                is_stalled = True
                stall_reason = f"no_progress_for_{time_since_progress:.0f}s"
                stall_info['stall_warnings'] += 1
            elif time_since_start > 600 and current_progress < 10.0:  # 10 minutes with less than 10% progress
                is_stalled = True
                stall_reason = f"slow_start_{time_since_start:.0f}s"
                stall_info['stall_warnings'] += 1
            
            # Update stall detection info
            self._stall_detection[stall_key] = stall_info
            
            if is_stalled:
                logger.warning(f"Download stall detected for client {client_id}: {stall_reason} "
                             f"(progress: {current_progress:.1f}%, warnings: {stall_info['stall_warnings']})")
            
            return is_stalled, stall_reason
            
        except Exception as e:
            logger.error(f"Error in stall detection for client {client_id}: {str(e)}")
            return False, "error"
    
    def _handle_download_stall(self, client_id, process, stall_reason):
        """Handle detected download stall with recovery mechanisms"""
        try:
            if not hasattr(self, '_stall_detection'):
                return False
            
            stall_key = f"{client_id}_stall_detection"
            stall_info = self._stall_detection.get(stall_key, {})
            
            recovery_attempts = stall_info.get('recovery_attempts', 0)
            stall_warnings = stall_info.get('stall_warnings', 0)
            
            logger.info(f"Attempting stall recovery for client {client_id}: {stall_reason} "
                       f"(attempt: {recovery_attempts + 1}, warnings: {stall_warnings})")
            
            # Recovery strategy based on stall severity and attempts
            if recovery_attempts == 0:
                # First attempt: Send SIGTERM to process (gentle termination)
                try:
                    if process and process.poll() is None:
                        logger.info(f"Sending SIGTERM to stalled process for client {client_id}")
                        process.terminate()
                        
                        # Wait a bit for graceful termination
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            logger.warning(f"Process did not terminate gracefully for client {client_id}")
                        
                        # Activate fallback progress to maintain user feedback
                        progress_state = self.get_or_create_progress_state(client_id)
                        progress_state.activate_fallback()
                        
                        stall_info['recovery_attempts'] = 1
                        self._stall_detection[stall_key] = stall_info
                        return True
                        
                except Exception as e:
                    logger.error(f"Error terminating stalled process for client {client_id}: {str(e)}")
            
            elif recovery_attempts == 1:
                # Second attempt: Force kill process
                try:
                    if process and process.poll() is None:
                        logger.warning(f"Force killing stalled process for client {client_id}")
                        process.kill()
                        
                        # Activate fallback progress
                        progress_state = self.get_or_create_progress_state(client_id)
                        progress_state.activate_fallback()
                        
                        stall_info['recovery_attempts'] = 2
                        self._stall_detection[stall_key] = stall_info
                        return True
                        
                except Exception as e:
                    logger.error(f"Error killing stalled process for client {client_id}: {str(e)}")
            
            else:
                # Multiple recovery attempts failed - give up and report error
                logger.error(f"Multiple stall recovery attempts failed for client {client_id}")
                return False
            
            return False
            
        except Exception as e:
            logger.error(f"Error in stall recovery for client {client_id}: {str(e)}")
            return False
    
    def _reset_stall_detection(self, client_id):
        """Reset stall detection tracking for a client"""
        if hasattr(self, '_stall_detection'):
            stall_key = f"{client_id}_stall_detection"
            if stall_key in self._stall_detection:
                del self._stall_detection[stall_key]
    
    def _build_enhanced_progress_payload(self, client_id, progress, message, url, speed, eta, total_size, metadata, throttling_config):
        """Build enhanced progress payload with rich metadata"""
        payload = {
            "status": "downloading",
            "client_id": client_id,
            "progress": round(progress, 2),  # Round to 2 decimal places for consistency
            "message": message,
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "worker": socket.gethostname()
        }
        
        # Add rich metadata - speed, ETA, file size
        if speed and speed != 'N/A' and speed.strip():
            payload["download_speed"] = speed
        if eta and eta != 'N/A' and eta != '00:00' and eta.strip():
            payload["eta"] = eta
        if total_size and total_size.strip():
            payload["file_size"] = total_size
        
        # Add progress type indicators and enhanced metadata
        if metadata:
            payload["progress_type"] = metadata.get("progress_type", "real")
            payload["fallback_active"] = metadata.get("fallback_active", False)
            payload["current_phase"] = metadata.get("current_phase", "downloading")
            payload["is_stalled"] = metadata.get("is_stalled", False)
            
            # Add additional metadata for debugging and monitoring
            if metadata.get("time_since_start"):
                payload["elapsed_time"] = round(metadata["time_since_start"], 1)
            
            # Add fallback-specific metadata
            if metadata.get("fallback_active"):
                if metadata.get("fallback_phase"):
                    payload["fallback_phase"] = metadata["fallback_phase"]
                if metadata.get("estimated_duration"):
                    payload["estimated_duration"] = metadata["estimated_duration"]
        else:
            payload["progress_type"] = "real"
            payload["fallback_active"] = False
            payload["current_phase"] = "downloading"
            payload["is_stalled"] = False
        
        # Add throttling information for debugging
        payload["throttling_config"] = {
            "min_time_diff": throttling_config["min_time_diff"],
            "min_progress_diff": throttling_config["min_progress_diff"]
        }
        
        return payload
    
    def _send_progress_request(self, client_id, payload, request_start_time):
        """Send progress update request with enhanced error handling, graceful degradation, and retry mechanisms"""
        # Initialize WebSocket failure tracking if not exists
        if not hasattr(self, '_websocket_failure_tracking'):
            self._websocket_failure_tracking = {}
        
        client_key = f"{client_id}_websocket_failures"
        failure_info = self._websocket_failure_tracking.get(client_key, {
            'consecutive_failures': 0,
            'total_failures': 0,
            'last_failure_time': None,
            'circuit_breaker_until': None,
            'degraded_mode': False,
            'retry_attempts': 0
        })
        
        # Check circuit breaker
        current_time = datetime.now()
        if failure_info.get('circuit_breaker_until') and current_time < failure_info['circuit_breaker_until']:
            logger.debug(f"Circuit breaker active for client {client_id}, skipping WebSocket update")
            return False
        
        # Determine timeout and retry strategy based on connection quality and failure history
        connection_quality = payload.get("throttling_config", {}).get("connection_quality", "good")
        base_timeout = 10 if connection_quality == "poor" else 5
        
        # Adjust timeout based on failure history
        if failure_info['consecutive_failures'] > 0:
            timeout = min(base_timeout * (1 + failure_info['consecutive_failures'] * 0.5), 30)
        else:
            timeout = base_timeout
        
        # Determine retry attempts based on failure severity
        max_retries = 2 if failure_info['consecutive_failures'] < 3 else 1
        
        # Attempt to send with retries
        for attempt in range(max_retries + 1):
            try:
                # Add attempt information to payload for debugging
                payload_with_attempt = payload.copy()
                payload_with_attempt["websocket_attempt"] = attempt + 1
                payload_with_attempt["websocket_failures"] = failure_info['consecutive_failures']
                
                response = requests.post(
                    f"{FASTAPI_URL}/status/{client_id}",
                    json=payload_with_attempt,
                    timeout=timeout
                )
                response.raise_for_status()
                
                # Success - reset failure tracking
                self._reset_websocket_failure_tracking(client_id)
                return True
                
            except requests.exceptions.Timeout as e:
                error_type = "timeout"
                error_msg = f"Progress update timeout for client {client_id} (timeout: {timeout}s, attempt: {attempt + 1})"
                if attempt < max_retries:
                    logger.warning(f"{error_msg} - retrying...")
                    continue
                else:
                    logger.warning(error_msg)
                    
            except requests.exceptions.ConnectionError as e:
                error_type = "connection"
                error_msg = f"Connection error sending progress update for client {client_id} (attempt: {attempt + 1}): {str(e)}"
                if attempt < max_retries:
                    logger.warning(f"{error_msg} - retrying...")
                    continue
                else:
                    logger.warning(error_msg)
                    
            except requests.exceptions.HTTPError as e:
                error_type = "http"
                error_msg = f"HTTP error sending progress update for client {client_id} (attempt: {attempt + 1}): {e}"
                # Don't retry on HTTP errors (4xx, 5xx) as they're likely persistent
                logger.error(error_msg)
                break
                
            except Exception as e:
                error_type = "unexpected"
                error_msg = f"Unexpected error sending progress update for client {client_id} (attempt: {attempt + 1}): {str(e)}"
                if attempt < max_retries:
                    logger.warning(f"{error_msg} - retrying...")
                    continue
                else:
                    logger.error(error_msg)
        
        # All attempts failed - update failure tracking and implement graceful degradation
        self._handle_websocket_failure(client_id, error_type, error_msg)
        return False
    
    def _reset_websocket_failure_tracking(self, client_id):
        """Reset WebSocket failure tracking on successful send"""
        if hasattr(self, '_websocket_failure_tracking'):
            client_key = f"{client_id}_websocket_failures"
            if client_key in self._websocket_failure_tracking:
                # Keep total failures for statistics but reset consecutive failures
                self._websocket_failure_tracking[client_key]['consecutive_failures'] = 0
                self._websocket_failure_tracking[client_key]['circuit_breaker_until'] = None
                self._websocket_failure_tracking[client_key]['degraded_mode'] = False
                self._websocket_failure_tracking[client_key]['retry_attempts'] = 0
    
    def _handle_websocket_failure(self, client_id, error_type, error_msg):
        """Handle WebSocket failures with graceful degradation strategies"""
        if not hasattr(self, '_websocket_failure_tracking'):
            self._websocket_failure_tracking = {}
        
        client_key = f"{client_id}_websocket_failures"
        failure_info = self._websocket_failure_tracking.get(client_key, {
            'consecutive_failures': 0,
            'total_failures': 0,
            'last_failure_time': None,
            'circuit_breaker_until': None,
            'degraded_mode': False,
            'retry_attempts': 0
        })
        
        # Update failure statistics
        failure_info['consecutive_failures'] += 1
        failure_info['total_failures'] += 1
        failure_info['last_failure_time'] = datetime.now()
        failure_info['retry_attempts'] += 1
        
        # Implement graceful degradation strategies
        if failure_info['consecutive_failures'] >= 5:
            # Activate circuit breaker for 60 seconds after 5 consecutive failures
            failure_info['circuit_breaker_until'] = datetime.now() + timedelta(seconds=60)
            logger.warning(f"WebSocket circuit breaker activated for client {client_id} (60 seconds)")
            
        elif failure_info['consecutive_failures'] >= 3:
            # Enter degraded mode - reduce update frequency
            failure_info['degraded_mode'] = True
            logger.warning(f"WebSocket degraded mode activated for client {client_id}")
        
        # Store updated failure info
        self._websocket_failure_tracking[client_key] = failure_info
        
        # Log failure summary for monitoring
        logger.error(f"WebSocket failure summary for client {client_id}: "
                    f"consecutive={failure_info['consecutive_failures']}, "
                    f"total={failure_info['total_failures']}, "
                    f"type={error_type}, "
                    f"degraded_mode={failure_info['degraded_mode']}")
    
    def _is_websocket_degraded(self, client_id):
        """Check if WebSocket is in degraded mode for this client"""
        if not hasattr(self, '_websocket_failure_tracking'):
            return False
        
        client_key = f"{client_id}_websocket_failures"
        failure_info = self._websocket_failure_tracking.get(client_key, {})
        return failure_info.get('degraded_mode', False)

    def download_file(self, url, client_id):
        """Download a file using yt-dlp with enhanced progress system integration"""
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
        
        try:
            # Initialize progress state for this download
            progress_state = self.get_or_create_progress_state(client_id)
            
            # Set estimated duration if we can determine it from URL patterns
            estimated_duration = self._estimate_download_duration(url)
            if estimated_duration:
                progress_state.set_estimated_duration(estimated_duration)
            
            # Send download started status with initial progress
            self.send_status_update(client_id, "downloading", "Download started", url=url)
            
            # Start progress monitoring - this will activate fallback if no real progress is detected
            self._start_progress_monitoring(client_id, url)
            
            # Get platform-specific format
            format_selector = self.get_format_for_platform(url)
            
            # Build yt-dlp command with platform-appropriate format selection
            cmd = [
                'yt-dlp',
                '--newline',  # Ensure progress is output with newlines
                '--no-playlist',
                '--format', format_selector,
                '--output', output_template,
                '--print', 'after_move:filepath',
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
            
            # Monitor progress in real-time with enhanced state management
            stdout_lines = []
            stderr_lines = []
            progress_state = self.get_or_create_progress_state(client_id)
            last_progress_update = datetime.now()
            
            # Read from both stdout and stderr simultaneously
            while True:
                # Check if process has finished
                if process.poll() is not None:
                    break
                
                # Read from both stdout and stderr
                stdout_line = process.stdout.readline()
                stderr_line = process.stderr.readline()
                
                if stdout_line:
                    stdout_line = stdout_line.strip()
                    stdout_lines.append(stdout_line)
                    # Parse progress from stdout
                    self.parse_progress_line(stdout_line, client_id, url)
                    # Check if this might be the final file path
                    if stdout_line and not stdout_line.startswith('[') and os.path.exists(stdout_line):
                        logger.info(f"Potential file path from stdout: {stdout_line}")
                
                if stderr_line:
                    stderr_line = stderr_line.strip()
                    stderr_lines.append(stderr_line)
                    # Parse progress from stderr
                    self.parse_progress_line(stderr_line, client_id, url)
                
                # Ensure regular progress updates even without yt-dlp output
                current_time = datetime.now()
                time_since_last_update = (current_time - last_progress_update).total_seconds()
                
                # Check for download stall and attempt recovery
                is_stalled, stall_reason = self._detect_download_stall(client_id, process)
                if is_stalled:
                    recovery_success = self._handle_download_stall(client_id, process, stall_reason)
                    if recovery_success:
                        logger.info(f"Stall recovery initiated for client {client_id}")
                        # Continue monitoring after recovery attempt
                    else:
                        logger.error(f"Stall recovery failed for client {client_id}, continuing with fallback")
                
                # Send periodic updates to maintain progress flow and activate fallback if needed
                if time_since_last_update >= 3.0:  # Every 3 seconds minimum
                    current_progress, metadata = self.manage_progress_coordination(client_id, None)
                    
                    # Add stall information to metadata
                    if metadata is None:
                        metadata = {}
                    metadata["is_stalled"] = is_stalled
                    metadata["stall_reason"] = stall_reason if is_stalled else None
                    
                    # Create appropriate message based on progress state
                    if metadata.get("fallback_active"):
                        if metadata.get("progress_type") == "simulated":
                            message = f"Downloading... {current_progress:.1f}% (estimated)"
                        else:
                            message = f"Downloading... {current_progress:.1f}% (continuing)"
                    elif is_stalled:
                        message = f"Downloading... {current_progress:.1f}% (recovering from stall)"
                    else:
                        message = f"Downloading... {current_progress:.1f}%"
                    
                    # Send update
                    self.send_throttled_progress_update(
                        client_id, current_progress, message, url, metadata=metadata
                    )
                    last_progress_update = current_time
            
            # Get any remaining output
            remaining_stdout, remaining_stderr = process.communicate()
            if remaining_stdout:
                for line in remaining_stdout.splitlines():
                    line = line.strip()
                    if line:
                        stdout_lines.append(line)
                        self.parse_progress_line(line, client_id, url)
                        if not line.startswith('[') and os.path.exists(line):
                            logger.info(f"Potential file path from remaining stdout: {line}")
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
                        '--newline',
                        '--no-playlist',
                        '--format', 'best',
                        '--output', output_template,
                        '--print', 'after_move:filepath',
                        url
                    ]
                    
                    # Add cookies to retry command too
                    if os.path.exists(COOKIES_FILE):
                        cmd_retry.extend(['--cookies', COOKIES_FILE])
                    else:
                        cmd_retry.extend(['--cookies-from-browser', 'chrome'])
                    
                    logger.info(f"Retry command: {' '.join(cmd_retry)}")
                    
                    # Execute retry
                    process_retry = subprocess.Popen(
                        cmd_retry,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True
                    )
                    
                    # Monitor retry progress with enhanced state management
                    stdout_lines_retry = []
                    stderr_lines_retry = []
                    retry_last_update = datetime.now()
                    
                    while True:
                        if process_retry.poll() is not None:
                            break
                        
                        stdout_line = process_retry.stdout.readline()
                        stderr_line = process_retry.stderr.readline()
                        
                        if stdout_line:
                            stdout_lines_retry.append(stdout_line)
                            self.parse_progress_line(stdout_line.strip(), client_id, url)
                        
                        if stderr_line:
                            stderr_lines_retry.append(stderr_line)
                            self.parse_progress_line(stderr_line.strip(), client_id, url)
                        
                        # Ensure regular progress updates during retry
                        current_time = datetime.now()
                        time_since_last_update = (current_time - retry_last_update).total_seconds()
                        
                        if time_since_last_update >= 3.0:  # Every 3 seconds
                            current_progress, metadata = self.manage_progress_coordination(client_id, None)
                            
                            # Create retry-specific message
                            if metadata.get("fallback_active"):
                                message = f"Retrying download... {current_progress:.1f}% (estimated)"
                            else:
                                message = f"Retrying download... {current_progress:.1f}%"
                            
                            self.send_throttled_progress_update(
                                client_id, current_progress, message, url, metadata=metadata
                            )
                            retry_last_update = current_time
                    
                    # Get remaining output
                    remaining_stdout_retry, remaining_stderr_retry = process_retry.communicate()
                    if remaining_stdout_retry:
                        stdout_lines_retry.extend(remaining_stdout_retry.splitlines())
                        for line in remaining_stdout_retry.splitlines():
                            self.parse_progress_line(line.strip(), client_id, url)
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
                            
                            # Send final progress update for retry success
                            final_progress, metadata = self.manage_progress_coordination(client_id, 100.0)
                            self.send_throttled_progress_update(
                                client_id, 100.0, "Download completed (retry successful)", url, metadata=metadata
                            )
                            
                            # Log progress parsing statistics for this download
                            self.log_progress_statistics(client_id)
                            
                            # Transition to processing phase
                            self.send_status_update(client_id, "processing", "Uploading to cloud storage", url=url)
                            return file_path, temp_dir
                    
                    # If retry also failed, log both errors
                    logger.error(f"Retry also failed: {result_retry.stderr}")
                    error_msg = f"Download failed even with fallback format. Original error: {result.stderr}"
                
                self.send_status_update(client_id, "error", error_msg, url=url)
                # Clean up progress state on error
                self.cleanup_progress_state(client_id)
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
                # Clean up progress state on error
                self.cleanup_progress_state(client_id)
                return None, temp_dir
                
            logger.info(f"Download completed: {file_path}")
            
            # Send final progress update before transitioning to processing
            progress_state = self.get_or_create_progress_state(client_id)
            final_progress, metadata = self.manage_progress_coordination(client_id, 100.0)
            
            # Send completion progress update
            self.send_throttled_progress_update(
                client_id, 100.0, "Download completed", url, metadata=metadata
            )
            
            # Log progress parsing statistics for this download
            self.log_progress_statistics(client_id)
            
            # Clean up error handling tracking for this client
            self._reset_stall_detection(client_id)
            self._reset_websocket_failure_tracking(client_id)
            self._reset_parsing_failure_count(client_id)
            
            # Transition to processing phase
            self.send_status_update(client_id, "processing", "Uploading to cloud storage", url=url)
            
            return file_path, temp_dir
            
        except subprocess.TimeoutExpired:
            error_msg = "Download timed out after 1 hour"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg, url=url)
            # Clean up progress state on error
            self.cleanup_progress_state(client_id)
            return None, temp_dir
        except Exception as e:
            error_msg = f"Download error: {str(e)}"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", error_msg, url=url)
            # Clean up progress state on error
            self.cleanup_progress_state(client_id)
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

    def upload_to_gcs(self, file_path, client_id, url=None, video_metadata=None):
        """Upload file to Google Cloud Storage with video title-based filename"""
        try:
            original_filename = os.path.basename(file_path)
            file_extension = os.path.splitext(original_filename)[1]
            
            # Generate filename based on video metadata
            if video_metadata and video_metadata.get('title'):
                # Create a slugified filename from the video title
                title_slug = slugify(video_metadata['title'], max_length=80)
                
                # Add uploader if available (but keep it short)
                if video_metadata.get('uploader'):
                    uploader_slug = slugify(video_metadata['uploader'], max_length=20)
                    base_filename = f"{title_slug}_by_{uploader_slug}"
                else:
                    base_filename = title_slug
                
                # Ensure we don't exceed reasonable filename length
                if len(base_filename) > 100:
                    base_filename = base_filename[:100]
                
                # Create the final filename with timestamp for uniqueness
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                unique_filename = f"{base_filename}_{timestamp}{file_extension}"
                
                logger.info(f"Generated filename from video title: {unique_filename}")
            else:
                # Fallback to original method if no metadata available
                unique_filename = f"{client_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{original_filename}"
                logger.info(f"Using fallback filename (no metadata): {unique_filename}")
            
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
            
            # Extract video metadata first (for better filename generation)
            self.send_status_update(client_id, "processing", "Extracting video information...", url=url)
            video_metadata = self.extract_video_metadata(url)
            
            if video_metadata:
                logger.info(f"Extracted video metadata for {client_id}: {video_metadata['title']}")
            else:
                logger.warning(f"Could not extract metadata for {client_id}, will use fallback filename")
            
            # Download the file
            file_path, temp_dir = self.download_file(url, client_id)
            if file_path:
                # Upload to GCS with video metadata for better filename
                download_url, file_name = self.upload_to_gcs(file_path, client_id, url, video_metadata)
                if download_url:
                    # Send success status with video title if available
                    success_message = f"Download completed successfully"
                    if video_metadata and video_metadata.get('title'):
                        success_message = f"Downloaded: {video_metadata['title']}"
                    
                    self.send_status_update(
                        client_id,
                        "completed",
                        success_message,
                        download_url,
                        file_name,
                        url
                    )
                    # Clean up progress state on successful completion
                    self.cleanup_progress_state(client_id)

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