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

# --- Configuration ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
PROJECT_ID = os.getenv('PROJECT_ID', 'hosting-shit')
SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION', 'yt-dlp-downloads-sub')
FASTAPI_URL = os.getenv('FASTAPI_URL', 'https://yt-dlp-server-578977081858.us-central1.run.app/')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'hosting-shit')
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/tmp/downloads')
COOKIES_FILE = os.getenv('COOKIES_FILE', 'cookies.txt')
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# --- Logging Setup ---
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('yt-dlp-worker')

progress_logger = logging.getLogger('yt-dlp-worker.progress')
progress_handler = logging.FileHandler('progress_debug.log')
progress_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
progress_logger.addHandler(progress_handler)
progress_logger.setLevel(logging.DEBUG)


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
                "duration_ratio": 0.1, "progress_range": (25.0, 35.0),
                "base_rate": 2.0, "variance": 0.1, "initial_burst": True
            },
            "downloading": {
                "duration_ratio": 0.75, "progress_range": (35.0, 85.0),
                "base_rate": 0.8, "variance": 0.2
            },
            "finalizing": {
                "duration_ratio": 0.15, "progress_range": (85.0, 95.0),
                "base_rate": 0.2, "variance": 0.4
            }
        }

        # Adaptive parameters
        self.download_patterns = {
            "small_file": {"duration": 60, "phases": {"initialization": 0.05, "downloading": 0.85, "finalizing": 0.1}},
            "medium_file": {"duration": 300, "phases": {"initialization": 0.1, "downloading": 0.75, "finalizing": 0.15}},
            "large_file": {"duration": 900, "phases": {"initialization": 0.15, "downloading": 0.7, "finalizing": 0.15}}
        }

        self._update_pattern()
        logger.info(f"Initialized fallback progress generator for client {client_id} with pattern: {self.pattern}")

    def _update_pattern(self):
        if self.estimated_duration <= 120:
            self.pattern = self.download_patterns["small_file"]
        elif self.estimated_duration <= 600:
            self.pattern = self.download_patterns["medium_file"]
        else:
            self.pattern = self.download_patterns["large_file"]

        for phase_name, phase_config in self.phases.items():
            if phase_name in self.pattern["phases"]:
                phase_config["duration_ratio"] = self.pattern["phases"][phase_name]

    def get_current_phase(self, elapsed_seconds):
        """Determine current phase based on elapsed time"""
        init_duration = self.estimated_duration * self.phases["initialization"]["duration_ratio"]
        download_duration = self.estimated_duration * self.phases["downloading"]["duration_ratio"]

        if elapsed_seconds <= init_duration:
            return "initialization"
        if elapsed_seconds <= init_duration + download_duration:
            return "downloading"
        return "finalizing"

    def calculate_phase_progress(self, phase_name, elapsed_seconds, phase_elapsed):
        """Calculate progress within a specific phase"""
        phase_config = self.phases[phase_name]
        min_progress, max_progress = phase_config["progress_range"]

        phase_duration = self.estimated_duration * phase_config["duration_ratio"]
        if phase_duration <= 0:
            return min_progress

        phase_progress_ratio = min(1.0, phase_elapsed / phase_duration)

        if phase_name == "initialization":
            if phase_elapsed < 2.0:  # First 2 seconds get rapid progress
                burst_progress = min(0.9, phase_elapsed / 2.0)
                adjusted_ratio = burst_progress + (phase_progress_ratio - burst_progress) * 0.2
            else:
                adjusted_ratio = 1 - (1 - phase_progress_ratio) ** 1.3
        elif phase_name == "downloading":
            adjusted_ratio = phase_progress_ratio ** 0.9
        else:  # finalizing
            adjusted_ratio = phase_progress_ratio ** 1.5

        progress_range = max_progress - min_progress
        target_progress = min_progress + (progress_range * adjusted_ratio)
        return min(max_progress, target_progress)

    def add_realistic_variance(self, base_progress, phase_name):
        """Add realistic variance to progress updates"""
        import random
        phase_config = self.phases[phase_name]
        variance = phase_config["variance"]
        variation = random.uniform(-variance, variance)
        adjusted_progress = base_progress + variation

        if adjusted_progress < self.current_progress - 0.5:
            adjusted_progress = self.current_progress - 0.1
        return adjusted_progress

    def update_progress(self):
        """Update and return current simulated progress"""
        current_time = datetime.now()
        elapsed_seconds = (current_time - self.start_time).total_seconds()

        new_phase = self.get_current_phase(elapsed_seconds)
        if new_phase != self.current_phase:
            logger.info(f"Progress phase transition for client {self.client_id}: {self.current_phase} -> {new_phase}")
            self.current_phase = new_phase

        init_duration = self.estimated_duration * self.phases["initialization"]["duration_ratio"]
        download_duration = self.estimated_duration * self.phases["downloading"]["duration_ratio"]

        if self.current_phase == "initialization":
            phase_elapsed = elapsed_seconds
        elif self.current_phase == "downloading":
            phase_elapsed = elapsed_seconds - init_duration
        else:  # finalizing
            phase_elapsed = elapsed_seconds - init_duration - download_duration

        target_progress = self.calculate_phase_progress(self.current_phase, elapsed_seconds, phase_elapsed)
        varied_progress = self.add_realistic_variance(target_progress, self.current_phase)

        time_since_last_update = (current_time - self.last_update_time).total_seconds()
        max_increment = self.phases[self.current_phase]["base_rate"] * time_since_last_update * 2

        if varied_progress > self.current_progress + max_increment:
            varied_progress = self.current_progress + max_increment

        if varied_progress < self.current_progress:
            varied_progress = self.current_progress + 0.1

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
        if new_estimate and abs(new_estimate - self.estimated_duration) > 60:
            old_estimate = self.estimated_duration
            self.estimated_duration = new_estimate
            self._update_pattern()
            logger.info(f"Adjusted duration estimate for client {self.client_id}: {old_estimate}s -> {new_estimate}s, new pattern: {self.pattern}")


class ProgressState:
    """Manages progress state for individual download clients"""

    def __init__(self, client_id):
        self.client_id = client_id
        self.real_progress = None
        self.simulated_progress = 0.0
        self.last_real_update = None
        self.fallback_active = False
        self.progress_history = []
        self.estimated_duration = None
        self.download_start_time = datetime.now()
        self.current_phase = "initializing"
        self.last_progress_value = 0.0
        self.stall_detection_time = None
        self.progress_type = "real"
        self.max_history_size = 10
        self.stall_timeout = 15.0
        self.fallback_timeout = 0.5
        self.fallback_generator = None

    def update_real_progress(self, progress, speed=None, eta=None, total_size=None):
        """Update with real progress data from yt-dlp"""
        if progress is None or not (0 <= progress <= 100):
            return False

        current_time = datetime.now()
        self.real_progress = progress
        self.last_real_update = current_time
        self.progress_type = "real"
        self.progress_history.append((current_time, progress))
        if len(self.progress_history) > self.max_history_size:
            self.progress_history.pop(0)

        if progress < 5: self.current_phase = "initializing"
        elif progress < 95: self.current_phase = "downloading"
        else: self.current_phase = "finalizing"

        if progress > self.last_progress_value:
            self.stall_detection_time = None
            self.last_progress_value = progress
        elif self.stall_detection_time is None:
            self.stall_detection_time = current_time

        if eta and self.estimated_duration is None:
            self.update_estimated_duration_from_eta(eta)

        if self.fallback_active and progress > self.simulated_progress:
            self.fallback_active = False
        return True

    def update_estimated_duration_from_eta(self, eta_str):
        """Update estimated duration based on ETA string"""
        try:
            parts = list(map(int, eta_str.split(':')))
            if len(parts) == 2: eta_seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 3: eta_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            else: return

            if self.real_progress and self.real_progress > 0:
                elapsed_time = (datetime.now() - self.download_start_time).total_seconds()
                if elapsed_time > 0:
                    estimated_total = (elapsed_time / self.real_progress) * 100
                    self.estimated_duration = int(estimated_total)
                    if self.fallback_generator:
                        self.fallback_generator.adjust_duration_estimate(self.estimated_duration)
                    logger.info(f"Updated estimated duration for client {self.client_id}: {self.estimated_duration}s based on ETA: {eta_str}")
        except (ValueError, ZeroDivisionError) as e:
            logger.debug(f"Could not parse ETA '{eta_str}' for duration estimation: {e}")

    def set_estimated_duration(self, duration_seconds):
        """Manually set estimated duration"""
        if duration_seconds and duration_seconds > 0:
            self.estimated_duration = duration_seconds
            if self.fallback_generator:
                self.fallback_generator.adjust_duration_estimate(duration_seconds)
            logger.info(f"Set estimated duration for client {self.client_id}: {duration_seconds}s")

    def get_current_progress(self):
        """Get the current progress value, handling fallback logic"""
        current_time = datetime.now()
        time_since_start = (current_time - self.download_start_time).total_seconds()
        
        should_fallback = False
        if self.last_real_update is None:
            if time_since_start > self.fallback_timeout:
                should_fallback = True
        else:
            time_since_update = (current_time - self.last_real_update).total_seconds()
            if time_since_update > self.stall_timeout:
                should_fallback = True

        if should_fallback and not self.fallback_active:
            self.activate_fallback()

        if self.fallback_active:
            return self.get_simulated_progress()
        if self.real_progress is not None:
            return self.real_progress
        return self.get_simulated_progress()

    def activate_fallback(self):
        """Activate fallback progress simulation"""
        if not self.fallback_active:
            self.fallback_active = True
            self.progress_type = "simulated" if self.real_progress is None else "hybrid"
            if self.fallback_generator is None:
                self.fallback_generator = FallbackProgressGenerator(self.client_id, self.estimated_duration)
            if self.real_progress is not None:
                self.fallback_generator.current_progress = self.real_progress
            logger.info(f"Activated fallback progress for client {self.client_id}")

    def get_simulated_progress(self):
        """Generate simulated progress using the fallback generator"""
        if self.fallback_generator is None:
            self.fallback_generator = FallbackProgressGenerator(self.client_id, self.estimated_duration)
        return self.fallback_generator.update_progress()

    def is_stalled(self):
        """Check if progress appears to be stalled"""
        if self.stall_detection_time is None: return False
        return (datetime.now() - self.stall_detection_time).total_seconds() > self.stall_timeout

    def get_progress_metadata(self):
        """Get metadata about current progress state"""
        metadata = {
            "progress_type": self.progress_type, "fallback_active": self.fallback_active,
            "current_phase": self.current_phase, "is_stalled": self.is_stalled(),
            "time_since_start": (datetime.now() - self.download_start_time).total_seconds(),
            "history_size": len(self.progress_history)
        }
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
        if len(self.progress_history) < 2: return True
        for i in range(1, len(self.progress_history)):
            if self.progress_history[i][1] < self.progress_history[i-1][1] - 1.0:
                logger.warning(f"Progress went backwards for client {self.client_id}: {self.progress_history[i-1][1]}% -> {self.progress_history[i][1]}%")
                return False
        return True

    def smooth_progress_updates(self):
        """Apply smoothing to progress updates to avoid jumps"""
        if len(self.progress_history) < 2: return self.real_progress
        recent_values = [entry[1] for entry in self.progress_history[-3:]]
        smoothed = sum(recent_values) / len(recent_values)
        if self.real_progress is not None and abs(smoothed - self.real_progress) > 5.0:
            return self.real_progress
        return smoothed


def slugify(text, max_length=100):
    """Convert a string to a filesystem-safe slug."""
    if not text: return "untitled"
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[\s/\\:*?"<>|\n\r\t]+', '-', text)
    text = text.strip('-')
    if len(text) > max_length:
        text = text[:max_length]
        if '-' in text:
            text = text.rsplit('-', 1)[0]
    return text or "untitled"


class DownloadWorker:
    def __init__(self):
        self._progress_stats = {'total_lines_processed': 0, 'successful_parses': 0, 'failed_parses': 0, 'pattern_matches': {}, 'validation_failures': 0}
        self._progress_states = {}
        self._initialize_gcloud_clients()
        self.bucket = self.storage_client.bucket(GCS_BUCKET_NAME)
        self.subscription_path = self.subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_NAME)

    def _initialize_gcloud_clients(self):
        """Initializes Google Cloud clients with appropriate credentials."""
        creds = None
        try:
            if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(
                    GOOGLE_APPLICATION_CREDENTIALS,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                logger.info(f"Using service account credentials from: {GOOGLE_APPLICATION_CREDENTIALS}")
            else:
                logger.info("Using Application Default Credentials.")
            
            self.subscriber = pubsub_v1.SubscriberClient(credentials=creds)
            self.storage_client = storage.Client(credentials=creds)
            logger.info("Successfully initialized Google Cloud clients.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud clients: {e}")
            raise

    def send_status_update(self, client_id, status, **kwargs):
        """Send status update to FastAPI server"""
        payload = {
            "status": status,
            "client_id": client_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "worker": socket.gethostname(),
            **kwargs
        }
        try:
            response = requests.post(f"{FASTAPI_URL}/status/{client_id}", json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Status update sent to client {client_id}: {status}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send status update for client {client_id}: {e}")

    def get_format_for_platform(self, url):
        """Get appropriate format string based on the platform"""
        url_lower = url.lower()
        if 'instagram.com' in url_lower: return 'best'
        if 'tiktok.com' in url_lower: return 'best[height<=1080]/best'
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower: return 'best[height<=1080]/best[ext=mp4]/best'
        if 'twitter.com' in url_lower or 'x.com' in url_lower: return 'best'
        return 'best[height<=1080]/best'

    def extract_video_metadata(self, url, client_id=None):
        """Extract video metadata using yt-dlp."""
        cmd = ['yt-dlp', '--dump-json', '--no-playlist', url]
        if os.path.exists(COOKIES_FILE):
            cmd.extend(['--cookies', COOKIES_FILE])
        else:
            cmd.extend(['--cookies-from-browser', 'chrome'])

        logger.info(f"Extracting metadata for: {url}")
        if client_id:
            progress, metadata = self.manage_progress_coordination(client_id, None)
            self.send_throttled_progress_update(client_id, progress, "Connecting to video source...", url, metadata=metadata)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
            metadata = json.loads(result.stdout)
            title = metadata.get('title', 'Untitled')
            logger.info(f"Extracted metadata - Title: {title}")
            if client_id:
                progress, meta = self.manage_progress_coordination(client_id, None)
                self.send_throttled_progress_update(client_id, progress, f"Found: {title[:50]}...", url, metadata=meta)
            return metadata
        except subprocess.TimeoutExpired:
            logger.warning(f"Metadata extraction timed out for: {url}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to extract metadata: {e.stderr}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse metadata JSON: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during metadata extraction: {e}")
        return None

    def parse_progress_line(self, line, client_id, url):
        """Parse progress information from yt-dlp output."""
        self._progress_stats['total_lines_processed'] += 1
        progress_patterns = [
            r'\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+([^\s]+)\s+at\s+([^\s]+)\s+ETA\s+([^\s]+)',
            r'\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+([^\s]+)\s+in\s+([^\s]+)',
            r'(\d+(?:\.\d+)?)%.*?at\s+([^\s]+)',
            r'(\d+(?:\.\d+)?)%.*?ETA\s+([^\s]+)',
            r'(\d+(?:\.\d+)?)%',
        ]
        
        has_progress_indicators = ('%' in line and any(k in line.lower() for k in ['download', 'eta', 'at', 'remaining'])) or '[download]' in line.lower()
        if not has_progress_indicators:
            progress_logger.debug(f"Line skipped (no progress indicators): {line}")
            return

        progress_logger.debug(f"Parsing progress line for client {client_id}: {line}")
        
        progress_data = {}
        for i, pattern in enumerate(progress_patterns):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                self._progress_stats['pattern_matches'][f"pattern_{i+1}"] = self._progress_stats['pattern_matches'].get(f"pattern_{i+1}", 0) + 1
                groups = match.groups()
                progress_data['progress'] = self._validate_progress(float(groups[0]), client_id)
                if len(groups) > 1: progress_data['size'] = self._sanitize_size(groups[1])
                if len(groups) > 2: progress_data['speed'] = self._sanitize_speed(groups[2])
                if len(groups) > 3: progress_data['eta'] = self._sanitize_eta(groups[3])
                break
        
        if 'progress' in progress_data:
            self._progress_stats['successful_parses'] += 1
            
            p, s, e, t = progress_data.get('progress'), progress_data.get('speed'), progress_data.get('eta'), progress_data.get('size')
            managed_progress, metadata = self.manage_progress_coordination(client_id, p, s, e, t)
            
            message = f"Downloading... {managed_progress:.1f}%"
            if s: message += f" at {s}"
            if e: message += f" ETA {e}"

            self.send_throttled_progress_update(client_id, managed_progress, message, url, speed=s, eta=e, total_size=t, metadata=metadata)
        else:
            progress_logger.debug(f"No progress percentage found in line: {line}")
            self._progress_stats['failed_parses'] += 1

    def _validate_progress(self, progress, client_id):
        if not (0 <= progress <= 100):
            logger.warning(f"Invalid progress {progress}% for client {client_id}, clamping.")
            self._progress_stats['validation_failures'] += 1
            return min(100.0, max(0.0, progress))
        return round(progress, 1)

    def _sanitize_string(self, value, pattern=None):
        if not value or value.lower() in ['n/a', 'unknown', '--']: return None
        value = value.strip()
        if pattern and not re.match(pattern, value): return None
        return value

    def _sanitize_speed(self, speed_str): return self._sanitize_string(speed_str, r'.*/s')
    def _sanitize_eta(self, eta_str): return self._sanitize_string(eta_str, r'^\d{1,2}:\d{2}(:\d{2})?$')
    def _sanitize_size(self, size_str): return self._sanitize_string(size_str, r'.*[KMGT]?i?B')

    def log_progress_statistics(self, client_id=None):
        stats = self._progress_stats
        if stats['total_lines_processed'] == 0: return
        success_rate = (stats['successful_parses'] / stats['total_lines_processed']) * 100
        log_msg = [f"Progress parsing statistics{' for client ' + client_id if client_id else ''}:",
                   f"  Success rate: {success_rate:.1f}% ({stats['successful_parses']}/{stats['total_lines_processed']})"]
        logger.info("\n".join(log_msg))

    def get_or_create_progress_state(self, client_id):
        if client_id not in self._progress_states:
            self._progress_states[client_id] = ProgressState(client_id)
            logger.info(f"Created new progress state for client {client_id}")
        return self._progress_states[client_id]

    def cleanup_progress_state(self, client_id):
        if client_id in self._progress_states:
            del self._progress_states[client_id]
            logger.info(f"Cleaned up progress state for client {client_id}")

    def _estimate_download_duration(self, url):
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower: return 300
        if 'instagram.com' in url_lower: return 120
        if 'tiktok.com' in url_lower: return 90
        if 'twitter.com' in url_lower or 'x.com' in url_lower: return 60
        return 240

    def _start_progress_monitoring(self, client_id, url):
        progress_state = self.get_or_create_progress_state(client_id)
        progress_state.activate_fallback()
        current_progress, metadata = self.manage_progress_coordination(client_id, None)
        self.send_throttled_progress_update(client_id, current_progress, "Preparing download...", url, metadata=metadata)
        logger.info(f"Started progress monitoring for client {client_id} with immediate fallback activation.")

    def _ensure_progress_continuity(self, client_id):
        progress_state = self.get_or_create_progress_state(client_id)
        current_progress = progress_state.get_current_progress()
        metadata = progress_state.get_progress_metadata()
        
        if progress_state.fallback_active and progress_state.real_progress is not None:
            if progress_state.real_progress > progress_state.get_simulated_progress():
                logger.info(f"Transitioning back to real progress for client {client_id}")
                progress_state.fallback_active = False
                progress_state.progress_type = "real"
        
        return current_progress, metadata

    def manage_progress_coordination(self, client_id, progress, speed=None, eta=None, total_size=None):
        progress_state = self.get_or_create_progress_state(client_id)
        if progress is not None:
            progress_state.update_real_progress(progress, speed, eta, total_size)
        
        current_progress, metadata = self._ensure_progress_continuity(client_id)
        
        if not progress_state.fallback_active and progress_state.real_progress is not None:
            smoothed_progress = progress_state.smooth_progress_updates()
            if abs(smoothed_progress - current_progress) > 0.1:
                logger.debug(f"Applied progress smoothing: {current_progress}% -> {smoothed_progress}%")
                current_progress = smoothed_progress
                
        return current_progress, metadata

    def send_throttled_progress_update(self, client_id, progress, message, url, **kwargs):
        # Simplified for brevity. The original logic is complex and can be a source of issues.
        # A simple time-based throttle is often sufficient.
        if not hasattr(self, '_last_update_times'): self._last_update_times = {}
        last_update = self._last_update_times.get(client_id, datetime.min)
        if (datetime.now() - last_update).total_seconds() < 2 and progress < 99:
            return

        self._last_update_times[client_id] = datetime.now()
        self.send_status_update(client_id, "downloading", message=message, url=url, progress=progress, **kwargs)

    def _run_download_command(self, cmd, client_id, url):
        """Runs a download command and monitors its progress."""
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)
        
        stdout_lines, stderr_lines = [], []
        
        # More efficient reading of process output
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            stdout_lines.append(line)
            self.parse_progress_line(line, client_id, url)

        for line in iter(process.stderr.readline, ''):
            line = line.strip()
            stderr_lines.append(line)
            self.parse_progress_line(line, client_id, url)
            
        process.wait()
        
        return process.returncode, '\n'.join(stdout_lines), '\n'.join(stderr_lines)

    def download_file(self, url, client_id):
        """Download a file using yt-dlp with enhanced progress and retry."""
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')

        try:
            progress_state = self.get_or_create_progress_state(client_id)
            estimated_duration = self._estimate_download_duration(url)
            progress_state.set_estimated_duration(estimated_duration)

            self.send_status_update(client_id, "downloading", message="Starting download...", url=url)
            
            def attempt_download(format_selector):
                cmd = ['stdbuf', '-o0', 'yt-dlp', '--newline', '--no-playlist', '--format', format_selector,
                       '--output', output_template, '--print', 'after_move:filepath', url]
                if os.path.exists(COOKIES_FILE): cmd.extend(['--cookies', COOKIES_FILE])
                else: cmd.extend(['--cookies-from-browser', 'chrome'])
                
                logger.info(f"Executing command: {' '.join(cmd)}")
                return self._run_download_command(cmd, client_id, url)

            returncode, stdout, stderr = attempt_download(self.get_format_for_platform(url))

            if returncode != 0 and "Requested format is not available" in stderr:
                logger.info("Retrying with 'best' format...")
                self.send_status_update(client_id, "downloading", message="Retrying with different format...", url=url)
                returncode, stdout, stderr = attempt_download('best')

            if returncode != 0:
                error_msg = f"Download failed: {stderr}"
                logger.error(error_msg)
                self.send_status_update(client_id, "error", message=error_msg, url=url)
                self.cleanup_progress_state(client_id)
                return None, temp_dir

            file_path = next((line for line in reversed(stdout.splitlines()) if line and os.path.exists(line)), None)
            if not file_path:
                file_path = next((os.path.join(root, f) for root, _, files in os.walk(temp_dir) for f in files if not f.startswith('.')), None)

            if not file_path:
                error_msg = "Download completed but file not found."
                logger.error(error_msg)
                self.send_status_update(client_id, "error", message=error_msg, url=url)
                self.cleanup_progress_state(client_id)
                return None, temp_dir

            logger.info(f"Download completed: {file_path}")
            self.send_throttled_progress_update(client_id, 100.0, "Download completed", url)
            self.log_progress_statistics(client_id)
            self.send_status_update(client_id, "processing", message="Uploading to cloud storage", url=url)
            return file_path, temp_dir

        except Exception as e:
            error_msg = f"Download error: {e}"
            logger.error(error_msg, exc_info=True)
            self.send_status_update(client_id, "error", message=error_msg, url=url)
            self.cleanup_progress_state(client_id)
            return None, temp_dir

    def create_tinyurl(self, long_url):
        """Create a TinyURL short link."""
        try:
            response = requests.get("http://tinyurl.com/api-create.php", params={'url': long_url}, timeout=10)
            response.raise_for_status()
            short_url = response.text.strip()
            if short_url.startswith('http'):
                logger.info(f"Created TinyURL: {short_url}")
                return short_url
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create TinyURL: {e}")
        return long_url

    def upload_to_gcs(self, file_path, client_id, url=None, video_metadata=None):
        """Upload file to GCS with a descriptive filename."""
        try:
            original_filename = os.path.basename(file_path)
            file_extension = os.path.splitext(original_filename)[1]
            
            base_filename = f"{client_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            if video_metadata and video_metadata.get('title'):
                title_slug = slugify(video_metadata['title'])
                base_filename = f"{title_slug}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

            unique_filename = f"{base_filename}{file_extension}"
            
            blob = self.bucket.blob(unique_filename)
            blob.upload_from_filename(file_path)
            
            signed_url = blob.generate_signed_url(expiration=timedelta(hours=24), version="v4")
            short_url = self.create_tinyurl(signed_url)
            
            logger.info(f"File uploaded to GCS: {unique_filename}")
            return short_url, unique_filename
        except Exception as e:
            error_msg = f"Upload failed: {e}"
            logger.error(error_msg)
            self.send_status_update(client_id, "error", message=error_msg, url=url)
            return None, None

    def process_message(self, message):
        """Process a Pub/Sub message."""
        temp_dir = None
        client_id = None
        try:
            data = json.loads(message.data.decode('utf-8'))
            url, client_id = data.get('url'), data.get('client_id')

            if not url or not client_id:
                logger.error("Invalid message: missing url or client_id")
                message.ack()
                return

            logger.info(f"Processing download request from {client_id}: {url}")
            
            self._start_progress_monitoring(client_id, url)
            self.send_status_update(client_id, "processing", message="Analyzing video...", url=url)
            video_metadata = self.extract_video_metadata(url, client_id)

            file_path, temp_dir = self.download_file(url, client_id)
            if file_path:
                download_url, file_name = self.upload_to_gcs(file_path, client_id, url, video_metadata)
                if download_url:
                    success_message = f"Downloaded: {video_metadata['title']}" if video_metadata else "Download completed successfully"
                    self.send_status_update(client_id, "completed", message=success_message, download_url=download_url, file_name=file_name, url=url)
                    self.cleanup_progress_state(client_id)

        except json.JSONDecodeError:
            logger.error("Invalid JSON in message")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            if client_id:
                self.send_status_update(client_id, "error", message=f"An unexpected error occurred: {e}")
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Cleaned up temp directory: {temp_dir}")
            message.ack()
            logger.info(f"Message processed: {message.message_id}")

    def run(self):
        """Start the worker."""
        logger.info(f"Starting yt-dlp worker, listening to {SUBSCRIPTION_NAME}")
        streaming_pull_future = self.subscriber.subscribe(self.subscription_path, self.process_message)
        logger.info("Listening for messages...")
        try:
            streaming_pull_future.result()
        except (KeyboardInterrupt, Exception) as e:
            streaming_pull_future.cancel()
            logger.info(f"Worker shutting down: {e}")

if __name__ == "__main__":
    worker = DownloadWorker()
    worker.run()