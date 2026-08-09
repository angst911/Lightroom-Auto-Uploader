import os
import requests
import json
import logging
import subprocess
import datetime
from typing import Optional, List
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TokenExpiredError(Exception):
    """The short-lived access token expired; a normal refresh will fix this."""
    pass

class RefreshTokenInvalidError(Exception):
    """The refresh token itself is dead (revoked/expired). Requires re-authentication
    via the /auth/start web flow -- a normal refresh cannot recover from this."""
    pass

def retry_on_token_expiry(func):
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except TokenExpiredError:
            logger.info(f"Retrying {func.__name__} with new token...")
            # Headers will auto-refresh on next call because _get_headers checks expires_at
            return func(self, *args, **kwargs)
    return wrapper

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

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 token_update_callback=None, on_auth_failure=None, on_auth_recovered=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = None
        self.access_token_expires_at = 0
        self.catalog_id = None
        self.account_id = None
        self.token_update_callback = token_update_callback
        # Called (once, until recovered) with an error message when the refresh
        # token itself is found to be dead -- not on routine access-token refreshes.
        self.on_auth_failure = on_auth_failure
        # Called (once) when a refresh succeeds after a prior auth-failure state.
        self.on_auth_recovered = on_auth_recovered
        # Starts broken if there's no refresh token yet at all (never authenticated),
        # not just when a previously-working token dies later.
        self.auth_broken = not bool(refresh_token)

    def update_refresh_token(self, new_refresh_token: str):
        """Called by the /auth/callback web flow after a successful manual re-auth.
        Hot-swaps the token in the running process -- no container restart needed."""
        self.refresh_token = new_refresh_token
        self.access_token = None
        self.access_token_expires_at = 0
        self.auth_broken = False
        if self.token_update_callback:
            self.token_update_callback(self.refresh_token)
        logger.info("Refresh token updated via manual re-authentication.")

    def refresh_access_token(self):
        if not self.refresh_token:
            # Never authenticated yet -- don't bother hitting the network.
            # auth_broken is already True from __init__ in this case, so this
            # won't re-fire on_auth_failure; it's an expected first-run state.
            raise RefreshTokenInvalidError("No refresh token configured yet. Authenticate via /auth/start.")
        logger.info("Refreshing access token...")
        import time
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        response = requests.post(self.IMS_URL, data=data, timeout=15)

        if response.status_code == 400:
            # The only things that vary in this specific request are the static
            # client_id/client_secret (if these were wrong, every refresh would
            # always have failed, not just now) and refresh_token -- so any 400
            # here means the refresh token itself is dead. Adobe's IMS doesn't
            # consistently use the standard OAuth2 `invalid_grant` error code for
            # this (observed `access_denied` for an expired token in practice),
            # so don't try to pattern-match the exact error string.
            try:
                err = response.json()
            except ValueError:
                err = {}
            error_code = err.get("error", "unknown_error")
            msg = err.get("error_description") or f"Adobe rejected the refresh token ({error_code})."
            logger.error(f"Refresh token is dead: {msg}")
            if not self.auth_broken:
                self.auth_broken = True
                if self.on_auth_failure:
                    self.on_auth_failure(msg)
            raise RefreshTokenInvalidError(msg)

        response.raise_for_status()
        res_data = response.json()

        self.access_token = res_data["access_token"]
        expires_in = res_data.get("expires_in", 86400)
        self.access_token_expires_at = time.time() + expires_in - 300

        if "refresh_token" in res_data:
            self.refresh_token = res_data["refresh_token"]
            logger.info("New refresh token received.")
            if self.token_update_callback:
                self.token_update_callback(self.refresh_token)
        logger.info(f"Access token refreshed. Expires in {expires_in}s.")

        if self.auth_broken:
            self.auth_broken = False
            if self.on_auth_recovered:
                self.on_auth_recovered()

    def _get_headers(self):
        import time
        if not self.access_token or time.time() > self.access_token_expires_at:
            self.refresh_access_token()
        return {
            "X-API-Key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _parse_lr_json(self, response_text: str):
        import re
        clean_text = re.sub(r'^while\s*\(1\)\s*\{\s*\}', '', response_text)
        return json.loads(clean_text)

    def _handle_error(self, response: requests.Response):
        if response.status_code == 401:
            logger.warning("Access token expired (401). Forcing refresh...")
            self.access_token = None
            self.access_token_expires_at = 0
            raise TokenExpiredError("Access token expired")

        try:
            error_data = self._parse_lr_json(response.text)
            logger.error(f"API Error ({response.status_code}): {json.dumps(error_data, indent=2)}")
        except:
            logger.error(f"API Error ({response.status_code}): {response.text}")
        response.raise_for_status()

    @retry_on_token_expiry
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

    @retry_on_token_expiry
    def get_catalog_id(self) -> str:
        if self.catalog_id:
            return self.catalog_id
        logger.info("Fetching catalog ID...")
        response = requests.get(f"{self.BASE_URL}/catalog", headers=self._get_headers())
        if response.status_code != 200:
            self._handle_error(response)
        data = self._parse_lr_json(response.text)
        self.catalog_id = data.get("id")
        if not self.catalog_id and "resources" in data:
            self.catalog_id = data["resources"][0]["id"]
        logger.info(f"Catalog ID: {self.catalog_id}")
        return self.catalog_id

    @retry_on_token_expiry
    def get_album_id(self, album_name: str) -> Optional[str]:
        catalog_id = self.get_catalog_id()
        logger.info(f"Searching for album: {album_name}")
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/albums"
        found_albums = []
        while url:
            response = requests.get(url, headers=self._get_headers())
            if response.status_code != 200:
                self._handle_error(response)
            data = self._parse_lr_json(response.text)
            for album in data.get("resources", []):
                if album.get("payload", {}).get("name") == album_name:
                    found_albums.append(album['id'])
            next_href = data.get("links", {}).get("next", {}).get("href")
            url = urljoin(url, next_href) if next_href else None
        if not found_albums:
            logger.info("Album not found.")
            return None
        if len(found_albums) > 1:
            logger.warning(f"Multiple albums found with name '{album_name}': {found_albums}")
        logger.info(f"Using album ID: {found_albums[0]}")
        return found_albums[0]

    @retry_on_token_expiry
    def create_album(self, album_name: str) -> str:
        catalog_id = self.get_catalog_id()
        logger.info(f"Creating album: {album_name}")
        import uuid
        album_id = uuid.uuid4().hex
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/albums/{album_id}"
        payload = {"subtype": "project", "serviceId": self.client_id, "payload": {"name": album_name}}
        response = requests.put(url, headers=self._get_headers(), json=payload)
        if response.status_code not in [200, 201]:
            self._handle_error(response)
        logger.info(f"Created album ID: {album_id}")
        return album_id

    @retry_on_token_expiry
    def find_asset_by_hash(self, sha256: str) -> Optional[str]:
        catalog_id = self.get_catalog_id()
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/assets"
        params = {"sha256": sha256}
        response = requests.get(url, headers=self._get_headers(), params=params)
        if response.status_code != 200:
            self._handle_error(response)
        data = self._parse_lr_json(response.text)
        resources = data.get("resources", [])
        return resources[0]["id"] if resources else None

    @retry_on_token_expiry
    def upload_photo(self, file_path: str, album_id: str):
        catalog_id = self.get_catalog_id()
        account_id = self.get_account_id()
        import uuid
        import hashlib
        file_name = os.path.basename(file_path)
        capture_date = get_capture_date(file_path)
        file_size = os.path.getsize(file_path)
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        sha256 = sha256_hash.hexdigest()
        
        existing_asset_id = self.find_asset_by_hash(sha256)
        if existing_asset_id:
            logger.info(f"Photo {file_name} already exists in Lightroom. Ensuring it's in the album...")
            self.add_to_album(album_id, existing_asset_id, file_name)
            return

        asset_id = uuid.uuid4().hex
        if capture_date != "0000-00-00T00:00:00" and not capture_date.endswith('Z'):
            capture_date += "Z"

        logger.info(f"Uploading {file_name} (Size: {file_size}) as asset {asset_id}...")
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
            return
        if response.status_code not in [200, 201]:
            self._handle_error(response)

        url = f"{self.BASE_URL}/catalogs/{catalog_id}/assets/{asset_id}/master"
        headers = self._get_headers()
        headers["Content-Type"] = "application/octet-stream"
        with open(file_path, "rb") as f:
            response = requests.put(url, headers=headers, data=f)
        if response.status_code not in [200, 201]:
            self._handle_error(response)

        self.add_to_album(album_id, asset_id, file_name)

    @retry_on_token_expiry
    def add_to_album(self, album_id: str, asset_id: str, file_name: str):
        catalog_id = self.get_catalog_id()
        url = f"{self.BASE_URL}/catalogs/{catalog_id}/albums/{album_id}/assets"
        payload = {"resources": [{"id": asset_id, "payload": {"order": "a0"}}]}
        response = requests.put(url, headers=self._get_headers(), json=payload)
        
        try:
            res_data = self._parse_lr_json(response.text)
            is_already_in_album = False
            if response.status_code == 403:
                is_already_in_album = True
            elif res_data.get('errors'):
                for err in res_data['errors']:
                    if err.get('http_status') == 403 or "already in album" in str(err.get('errors', {}).get('asset', [])):
                        is_already_in_album = True
                        break
            if is_already_in_album:
                logger.info(f"Asset {file_name} is already in the album.")
                return
        except:
            pass

        if response.status_code not in [200, 201, 204]:
            self._handle_error(response)
        logger.info(f"Successfully associated {file_name} with album.")
