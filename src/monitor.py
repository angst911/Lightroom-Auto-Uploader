import os
import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from lightroom import LightroomAPI
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

MONITOR_DIR = os.getenv("MONITOR_DIR", "/photos")
ALBUM_NAME = os.getenv("ALBUM_NAME", "Server_Auto_Upload")
DATA_DIR = os.getenv("DATA_DIR", "/data")
UPLOAD_LOG = os.path.join(DATA_DIR, "uploaded_files.log")
TOKEN_FILE = os.path.join(DATA_DIR, "refresh_token.txt")

def save_token(token: str):
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    logger.info(f"Saved new refresh token to {TOKEN_FILE}")

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    return os.getenv("ADOBE_REFRESH_TOKEN")

import hashlib

class PhotoHandler(FileSystemEventHandler):
    def __init__(self, lr_api: LightroomAPI, album_id: str):
        self.lr_api = lr_api
        self.album_id = album_id
        self.uploaded_hashes = self._load_uploaded_hashes()
        self.processing_files = set()

    def _load_uploaded_hashes(self):
        if os.path.exists(UPLOAD_LOG):
            with open(UPLOAD_LOG, "r") as f:
                return set(line.strip() for line in f)
        return set()

    def _log_uploaded_hash(self, file_hash: str):
        self.uploaded_hashes.add(file_hash)
        with open(UPLOAD_LOG, "a") as f:
            f.write(file_hash + "\n")

    def _get_file_hash(self, file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _wait_for_file_stability(self, file_path: str, timeout: int = 300, check_interval: int = 2) -> bool:
        """Waits until the file size remains constant for at least one interval."""
        last_size = -1
        start_time = time.time()
        
        logger.info(f"Waiting for file stability: {os.path.basename(file_path)}")
        
        while time.time() - start_time < timeout:
            try:
                if not os.path.exists(file_path):
                    return False
                    
                current_size = os.path.getsize(file_path)
                # If size is constant and > 0, we assume it's finished
                if current_size == last_size and current_size > 0:
                    logger.info(f"File stable at {current_size} bytes.")
                    return True
                
                last_size = current_size
            except OSError as e:
                logger.debug(f"Error checking file size for {file_path}: {e}")
            
            time.sleep(check_interval)
        
        logger.warning(f"Timeout waiting for file stability: {file_path}")
        return False

    def on_created(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self.process_file(event.dest_path)

    def process_file(self, file_path: str):
        # Filter for image files (including Canon CR3)
        ext = os.path.splitext(file_path)[1].lower()
        valid_extensions = [
            '.jpg', '.jpeg', '.png', '.dng', '.tiff', 
            '.cr3', '.cr2', '.arw', '.nef', '.orf'
        ]
        
        if ext not in valid_extensions:
            return

        if file_path in self.processing_files:
            return
            
        self.processing_files.add(file_path)
        
        try:
            # Wait for the file to be fully written (essential for SFTP)
            if not self._wait_for_file_stability(file_path):
                return

            file_hash = self._get_file_hash(file_path)
            if file_hash in self.uploaded_hashes:
                logger.info(f"File {os.path.basename(file_path)} already uploaded (local hash match). Skipping.")
                return

            # upload_photo now returns True if uploaded or already exists
            self.lr_api.upload_photo(file_path, self.album_id)
            # Log the hash so we don't check the API again for this file
            self._log_uploaded_hash(file_hash)
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
        finally:
            self.processing_files.discard(file_path)

def main():
    client_id = os.getenv("ADOBE_CLIENT_ID")
    client_secret = os.getenv("ADOBE_CLIENT_SECRET")
    refresh_token = load_token()

    if not all([client_id, client_secret, refresh_token]):
        logger.error("Missing Adobe API credentials in environment variables or token file.")
        return

    lr_api = LightroomAPI(
        client_id, 
        client_secret, 
        refresh_token, 
        token_update_callback=save_token
    )
    
    # Ensure album exists
    album_id = lr_api.get_album_id(ALBUM_NAME)
    if not album_id:
        album_id = lr_api.create_album(ALBUM_NAME)

    # Initial scan of the directory
    handler = PhotoHandler(lr_api, album_id)
    logger.info(f"Performing initial scan of {MONITOR_DIR}...")
    for root, _, files in os.walk(MONITOR_DIR):
        for file in files:
            handler.process_file(os.path.join(root, file))

    # Setup watchdog
    observer = Observer()
    observer.schedule(handler, MONITOR_DIR, recursive=False)
    observer.start()
    logger.info(f"Monitoring {MONITOR_DIR} for new photos...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
