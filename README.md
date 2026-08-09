# Lightroom Auto-Upload Container

This project provides a Docker container that monitors a folder for photos and automatically uploads them to Adobe Lightroom Cloud into a specific album.

## Setup Instructions

### 1. Adobe Developer Console
1.  Go to the [Adobe Developer Console](https://console.adobe.io/).
2.  Create a new project.
3.  Add the **Lightroom Services** API to the project. (Note: In the console, this may be listed under "Photoshop Lightroom" or simply "Lightroom Services").
4.  Add an **OAuth Web App** credential and configure it:
    *   **Default redirect URI**: the exact URL this service will be reachable at, e.g. `https://lightroomsync.anomaly.cx/auth/callback`. This appears to be what Adobe actually redirects the browser to at the end of login, regardless of the `redirect_uri` passed in the request — so it must be the real, working callback URL, not a placeholder.
    *   **Redirect URI pattern**: matching pattern for the same URL, e.g. `https://lightroomsync\.anomaly\.cx/auth/callback` (escape literal periods with `\`).
    *   All authentication — both the very first login and any later re-authentication — goes through this one URL. There's no separate local bootstrap step or second redirect URI to manage.
5.  Note your **Client ID** and **Client Secret**.

### 2. Configuration
1.  Copy `.env-example` to `.env`:
    ```bash
    cp .env-example .env
    ```
2.  Fill in your `ADOBE_CLIENT_ID` and `ADOBE_CLIENT_SECRET` in `.env`.
3.  Set `OAUTH_REDIRECT_BASE_URL` to the same URL registered above (minus the `/auth/callback` suffix, e.g. `https://lightroomsync.anomaly.cx`). Optionally set `DISCORD_WEBHOOK_URL` to get notified if authentication ever breaks.
4.  Leave `ADOBE_REFRESH_TOKEN` unset — it's not needed to start the container. Authentication (including the very first time) happens via the web endpoint below.

### 3. Running with Docker Compose
1.  Create the `photos` and `data` directories:
    ```bash
    mkdir -p photos data
    ```
2.  Start the container:
    ```bash
    docker-compose up -d
    ```

The container starts up fine with no refresh token yet — it just sits in an "authentication needed" state until you complete the step below.

### 4. Authenticating (first time and every time after)
1.  Visit `OAUTH_REDIRECT_BASE_URL/auth/start` (e.g. `https://lightroomsync.anomaly.cx/auth/start`) and log into Adobe.
2.  That's it — the token is picked up by the already-running process immediately, no restart needed. The initial directory scan (and any files that arrived before authentication was completed) will be picked up on the next filesystem event.

The container will then monitor the `./photos` directory. Any photos dropped into this folder will be automatically uploaded to the "Server_Auto_Upload" album in your Lightroom account.

If Adobe ever revokes/expires the refresh token later, the service detects this (rather than failing silently), sends a Discord alert if configured, and the fix is the same: visit `/auth/start` again.

`OAUTH_REDIRECT_BASE_URL` is intentionally kept LAN-internal (no public DNS record) since this endpoint can rebind which Adobe account the service uploads to.

## Structure
- `src/monitor.py`: Main logic for file monitoring and triggering uploads.
- `src/lightroom.py`: Wrapper for the Lightroom API, including token refresh and failure detection.
- `src/web.py`: OAuth2 authentication web endpoint (`/auth/start`, `/auth/callback`) — used for both first-time setup and later re-authentication.
- `data/uploaded_files.log`: Keeps track of uploaded files to avoid duplicates.
- `data/refresh_token.txt`: Current refresh token; updated automatically on every rotation and on successful (re-)auth.
- `photos/`: The directory to monitor (mapped to `/photos` in the container).
