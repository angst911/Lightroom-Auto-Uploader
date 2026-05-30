import os
import requests
import json
import logging
import subprocess
import datetime
from typing import Optional, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_capture_date(file_path: str) -> str:
    """Attempt to extract capture date using exiftool (best for CR3) or exifread."""
    # 1. Try ExifTool (Best for CR3)
    try:
        cmd = ['exiftool', '-j', '-DateTimeOriginal', '-CreateDate', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data:
                date_str = data[0].get('DateTimeOriginal') or data[0].get('CreateDate')
                if date_str:
                    # ExifTool format: "2023:10:24 14:30:05"
                    # Lightroom format: "YYYY-MM-DDTHH:MM:SS"
                    try:
                        dt = datetime.datetime.strptime(date_str[:19], "%Y:%m:%d %H:%M:%S")
                        return dt.isoformat()
                    except ValueError:
                        pass
    except Exception as e:
        logger.debug(f"ExifTool failed for {file_path}: {e}")

    # 2. Try ExifRead (Fallback for standard formats)
    try:
        import exifread
        with open(file_path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag='EXIF DateTimeOriginal', details=False)
            date_tag = tags.get('EXIF DateTimeOriginal')
            if date_tag:
                date_str = str(date_tag)
                try:
                    dt = datetime.datetime.strptime(date_str[:19], "%Y:%m:%d %H:%M:%S")
                    return dt.isoformat()
                except ValueError:
                    pass
    except Exception as e:
        logger.debug(f"ExifRead failed for {file_path}: {e}")

    return "0000-00-00T00:00:00"

class LightroomAPI:
    BASE_URL = "https://lr.adobe.io/v2"
    IMS_URL = "https://ims-na1.adobelogin.com/ims/token/v3"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, token_update_callback=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = None
        self.catalog_id = None
        self.account_id = None
        self.token_update_callback = token_update_callback

    def get_account_id(self) -> str:
        if self.account_id:
            return self.account_id
        
        logger.info("Fetching account ID...")
        response = requests.get(f"{self.BASE_URL}/account", headers=self._get_headers())
        if response.status_code != 200:
            self._handle_error(response)
        data = self._parse_lr_json(response.text)
        self.account_id = data.get("id")
        logger.info(f"Account ID: {self.account_id}")
        return self.account_id

    def refresh_access_token(self):
        logger.info("Refreshing access token...")
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        response = requests.post(self.IMS_URL, data=data)
        response.raise_for_status()
        res_data = response.json()
        self.access_token = res_data["access_token"]
        # Adobe sometimes returns a new refresh token
        if "refresh_token" in res_data:
            self.refresh_token = res_data["refresh_token"]
            logger.info("New refresh token received.")
            if self.token_update_callback:
                self.token_update_callback(self.refresh_token)
        logger.info("Access token refreshed.")

    def _get_headers(self):
        if not self.access_token:
            self.refresh_access_token()
        return {
            "X-API-Key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _parse_lr_json(self, response_text: str):
        # Lightroom API prepends 'while(1){}' or similar for security
        import re
        clean_text = re.sub(r'^while\s*\(1\)\s*\{\s*\}', '', response_text)
        return json.loads(clean_text)

    def get_catalog_id(self) -> str:
        if self.catalog_id:
            return self.catalog_id
        
        logger.info("Fetching catalog ID...")
        # Note: The metadata endpoint is singular 'catalog'
        response = requests.get(f"{self.BASE_URL}/catalog", headers=self._get_headers())
        if response.status_code != 200:
            self._handle_error(response)
        data = self._parse_lr_json(response.text)
        # For the singular endpoint, it's often directly in the root or 'id' field
        self.catalog_id = data.get("id")
        if not self.catalog_id and "resources" in data:
            self.catalog_id = data["resources"][0]["id"]
            
        logger.info(f"Catalog ID: {self.catalog_id}")
        return self.catalog_id

    def get_album_id(self, album_name: str) -> Optional[str]:
        catalog_id = self.get_catalog_id()
        logger.info(f"Searching for album: {album_name}")
        
        from urllib.parse import urljoin
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/albums"
        
        found_albums = []
        while url:
            response = requests.get(url, headers=self._get_headers())
            if response.status_code != 200:
                self._handle_error(response)
            
            data = self._parse_lr_json(response.text)
            
            for album in data.get("resources", []):
                name = album.get("payload", {}).get("name")
                if name == album_name:
                    found_albums.append(album['id'])
            
            # Check for next page
            next_href = data.get("links", {}).get("next", {}).get("href")
            if next_href:
                url = urljoin(url, next_href)
                logger.info(f"Fetching next page of albums: {url}")
            else:
                url = None
        
        if not found_albums:
            logger.info("Album not found.")
            return None
            
        if len(found_albums) > 1:
            logger.warning(f"Multiple albums found with name '{album_name}': {found_albums}")
            logger.warning("Using the first one found. Please delete duplicates in Lightroom Web.")
            
        logger.info(f"Using album ID: {found_albums[0]}")
        return found_albums[0]

    def create_album(self, album_name: str) -> str:
        catalog_id = self.get_catalog_id()
        logger.info(f"Creating album: {album_name}")
        
        import uuid
        album_id = uuid.uuid4().hex
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/albums/{album_id}"
        payload = {
            "subtype": "project",
            "serviceId": self.client_id,
            "payload": {
                "name": album_name
            }
        }
        response = requests.put(url, headers=self._get_headers(), json=payload)
        if response.status_code not in [200, 201]:
            self._handle_error(response)
        logger.info(f"Created album ID: {album_id}")
        return album_id

    def _handle_error(self, response: requests.Response):
        try:
            error_data = self._parse_lr_json(response.text)
            logger.error(f"API Error ({response.status_code}): {json.dumps(error_data, indent=2)}")
        except:
            logger.error(f"API Error ({response.status_code}): {response.text}")
        response.raise_for_status()

    def find_asset_by_hash(self, sha256: str) -> Optional[str]:
        catalog_id = self.get_catalog_id()
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/assets"
        params = {"sha256": sha256}
        
        response = requests.get(url, headers=self._get_headers(), params=params)
        if response.status_code != 200:
            self._handle_error(response)
            
        data = self._parse_lr_json(response.text)
        resources = data.get("resources", [])
        if resources:
            asset_id = resources[0]["id"]
            return asset_id
        return None

    def upload_photo(self, file_path: str, album_id: str):
        catalog_id = self.get_catalog_id()
        account_id = self.get_account_id()
        import uuid
        import hashlib
        file_name = os.path.basename(file_path)
        capture_date = get_capture_date(file_path)
        
        # Calculate file size and sha256
        file_size = os.path.getsize(file_path)
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        sha256 = sha256_hash.hexdigest()
        
        # 0. Explicit duplicate check
        existing_asset_id = self.find_asset_by_hash(sha256)
        if existing_asset_id:
            logger.info(f"Photo {file_name} already exists in Lightroom (API hash match). Ensuring it's in the album...")
            self.add_to_album(album_id, existing_asset_id, file_name)
            return

        asset_id = uuid.uuid4().hex
        # Ensure capture_date has Z if it's not the default
        if capture_date != "0000-00-00T00:00:00" and not capture_date.endswith('Z'):
            capture_date += "Z"

        logger.info(f"Uploading {file_name} (Size: {file_size}, SHA256: {sha256[:8]}...) as asset {asset_id}...")
        
        # 1. Create Metadata
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/assets/{asset_id}"
        payload = {
            "subtype": "image",
            "serviceId": self.client_id,
            "payload": {
                "captureDate": capture_date,
                "importSource": {
                    "fileName": file_name,
                    "fileSize": file_size,
                    "sha256": sha256,
                    "importedBy": account_id,
                    "importedOnDevice": "Docker Auto Uploader",
                    "importTimestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                }
            }
        }
        response = requests.put(url, headers=self._get_headers(), json=payload)
        
        if response.status_code == 412:
            logger.info(f"Photo {file_name} already exists in Lightroom (API 412 match). Skipping.")
            return

        if response.status_code not in [200, 201]:
            self._handle_error(response)

        # 2. Upload Binary
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/assets/{asset_id}/master"
        headers = self._get_headers()
        headers["Content-Type"] = "application/octet-stream"

        with open(file_path, "rb") as f:
            response = requests.put(url, headers=headers, data=f)
        if response.status_code not in [200, 201]:
            self._handle_error(response)

        # 3. Add to Album
        self.add_to_album(album_id, asset_id, file_name)

    def add_to_album(self, album_id: str, asset_id: str, file_name: str):
        catalog_id = self.get_catalog_id()
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/albums/{album_id}/assets"
        payload = {
            "resources": [{
                "id": asset_id,
                "payload": {
                    "order": "a0"
                }
            }]
        }
        response = requests.put(url, headers=self._get_headers(), json=payload)
        
        # Parse response body robustly
        try:
            res_data = self._parse_lr_json(response.text)
            
            # Check for "already in album" error which returns 403
            is_already_in_album = False
            if response.status_code == 403:
                is_already_in_album = True
            elif res_data.get('errors'):
                for err in res_data['errors']:
                    if err.get('http_status') == 403 or "already in album" in str(err.get('errors', {}).get('asset', [])):
                        is_already_in_album = True
                        break
            
            if is_already_in_album:
                logger.info(f"Asset {file_name} is already in the album. Skipping association.")
                return
                
            logger.debug(f"Album association response: {json.dumps(res_data)}")
        except Exception as e:
            logger.debug(f"Failed to parse album response: {e}")

        if response.status_code not in [200, 201, 204]:
            self._handle_error(response)
        
        logger.info(f"Successfully associated {file_name} with album.")
