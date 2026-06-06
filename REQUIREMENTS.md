# Lightroom Auto-Sync Service: Requirements & Specifications

This document outlines the core requirements and architectural decisions for the Lightroom Auto-Sync service. All future updates must comply with these specifications to maintain the integrity and reliability of the sync process.

## 1. Functional Requirements

### 1.1 Automated Monitoring
*   The service must monitor a designated directory (`/photos`) for new image files in real-time.
*   The monitor must handle `created`, `modified`, and `moved` events to capture files arriving via various transfer methods (specifically SFTP).

### 1.2 SFTP Stability Handling
*   The service must implement a "File Stability Check" to prevent processing files that are still being written by the camera.
*   **Specification:** A file is considered stable only when its file size remains unchanged for a minimum of 2 seconds.
*   **Timeout:** The stability check should timeout after 5 minutes if the file remains unstable.

### 1.3 Photo Metadata Extraction
*   The service must extract the `Capture Date` from photos to ensure they appear correctly in the Lightroom timeline.
*   **Canon CR3 Support:** The service must use `exiftool` as the primary method for extracting metadata from Canon CR3 RAW files.
*   **Fallback:** If `exiftool` fails, it should fallback to `exifread` for standard formats (JPG, TIFF).
*   **Default:** If no date is found, it must default to `0000-00-00T00:00:00`.

### 1.4 Dual-Layer Duplicate Detection
*   **Local Layer:** The service must maintain a persistent log (`data/uploaded_files.log`) of SHA-256 hashes of all successfully processed files.
*   **Cloud Layer:** Before uploading, the service must query the Lightroom API (`GET /assets?sha256=...`) to check if the photo already exists in the cloud catalog.
*   **Graceful Skips:** If a duplicate is found in either layer, the service must skip the upload but ensure the photo is associated with the target album.

### 1.5 Album Management
*   The service must sync all photos into a specific album (default: `Server_Auto_Upload`).
*   **Pagination:** The service must handle paginated album lists from Adobe to ensure it can find the target album regardless of how many albums exist in the account.
*   **User Album Preference:** The service should prefer existing user-created albums to "Partner" albums to ensure visibility in the Lightroom UI.

## 2. Technical Requirements

### 2.1 Authentication & Token Lifecycle
*   **Method:** Must use OAuth2 **Web App** flow to support long-lived Refresh Tokens.
*   **Proactive Refresh:** The service must track the Access Token expiration time and refresh it automatically before it expires.
*   **Reactive Recovery:** The service must catch `401 Unauthorized` errors, force a token refresh, and automatically retry the failed operation.
*   **Persistence:** Updated Refresh Tokens must be saved to `data/refresh_token.txt` to survive container restarts.

### 2.2 API Communication
*   **Base URL:** `https://lr.adobe.io/v2`
*   **Security:** All JSON responses from Adobe must be parsed after stripping the `while(1){}` security prefix.
*   **Error Handling:** All non-success API responses must log the full response body to aid in debugging.

### 2.3 Containerization
*   The service must be fully containerized using Docker and managed via `docker-compose`.
*   The Docker image must include `exiftool` and necessary Python dependencies.
*   Volumes must be used for `/photos` (source) and `/data` (persistence).

## 3. Supported Formats
The service must explicitly support and filter for the following extensions:
*   RAW: `.cr3`, `.cr2`, `.arw`, `.nef`, `.orf`, `.dng`
*   Standard: `.jpg`, `.jpeg`, `.png`, `.tiff`

---
*Last Updated: May 30, 2026*
