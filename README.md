# Lightroom Auto-Upload Container

This project provides a Docker container that monitors a folder for photos and automatically uploads them to Adobe Lightroom Cloud into a specific album.

## Setup Instructions

### 1. Adobe Developer Console
1.  Go to the [Adobe Developer Console](https://console.adobe.io/).
2.  Create a new project.
3.  Add the **Lightroom Services** API to the project. (Note: In the console, this may be listed under "Photoshop Lightroom" or simply "Lightroom Services").
4.  Configure OAuth2 and add **both** of these redirect URIs (one for the one-time local bootstrap, one for the self-service web re-auth endpoint the running service exposes):
    *   `https://localhost/` (pattern `https://localhost/.*`) — used once, by `auth_helper.py`, to get the very first refresh token.
    *   `https://lightroomsync.anomaly.cx/auth/callback` (or whatever `OAUTH_REDIRECT_BASE_URL` you configure) — used by the running service any time the refresh token needs to be replaced later.
5.  Note your **Client ID** and **Client Secret**.

### 2. Configuration
1.  Copy `.env-example` to `.env`:
    ```bash
    cp .env-example .env
    ```
2.  Fill in your `ADOBE_CLIENT_ID` and `ADOBE_CLIENT_SECRET` in `.env`.
3.  Set `OAUTH_REDIRECT_BASE_URL` to the URL this service will be reachable at (must exactly match a redirect URI registered above). Optionally set `DISCORD_WEBHOOK_URL` to get notified if authentication ever breaks.

### 3. Initial Authentication (one-time bootstrap only)
Since this is a background service, you need to perform a one-time authentication to get the *first* refresh token. After this, re-authentication (e.g. if Adobe revokes/expires the token) is self-service via the web endpoint described below — you should not need to run this script again.

1.  Install dependencies locally (requires Python):
    ```bash
    pip install -r requirements.txt
    ```
2.  Run the authentication helper:
    ```bash
    python src/auth_helper.py
    ```
3.  Follow the instructions in the terminal to get your `ADOBE_REFRESH_TOKEN` and add it to your `.env` file.

### 4. Running with Docker Compose
1.  Create the `photos` and `data` directories:
    ```bash
    mkdir -p photos data
    ```
2.  Start the container:
    ```bash
    docker-compose up -d
    ```

The container will now monitor the `./photos` directory. Any photos dropped into this folder will be automatically uploaded to the "Server_Auto_Upload" album in your Lightroom account.

### 5. Re-authenticating later (self-service, no shell access needed)
Adobe refresh tokens can expire or be revoked. The service tracks this and, if it happens:
*   It stops uploading and logs a clear "authentication is broken" message instead of failing silently.
*   It sends a Discord alert (if `DISCORD_WEBHOOK_URL` is set), including a direct link to re-auth.
*   Visit `OAUTH_REDIRECT_BASE_URL/auth/start` (e.g. `https://lightroomsync.anomaly.cx/auth/start`), log into Adobe, and you're done — no copying codes out of a dead localhost page, no editing `.env`, no restarting the container. The new token takes effect immediately and any files that failed to upload while auth was broken will be retried automatically once the next filesystem event fires for them.
*   `OAUTH_REDIRECT_BASE_URL` is intentionally kept LAN-internal (no public DNS record) since this endpoint can rebind which Adobe account the service uploads to.

## Structure
- `src/monitor.py`: Main logic for file monitoring and triggering uploads.
- `src/lightroom.py`: Wrapper for the Lightroom API, including token refresh and failure detection.
- `src/web.py`: Self-service OAuth2 re-authentication web endpoint (`/auth/start`, `/auth/callback`).
- `src/auth_helper.py`: One-time bootstrap script for the very first OAuth2 authentication.
- `data/uploaded_files.log`: Keeps track of uploaded files to avoid duplicates.
- `data/refresh_token.txt`: Current refresh token; updated automatically on every rotation and on successful re-auth.
- `photos/`: The directory to monitor (mapped to `/photos` in the container).
