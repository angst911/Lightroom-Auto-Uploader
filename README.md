# Lightroom Auto-Upload Container

This project provides a Docker container that monitors a folder for photos and automatically uploads them to Adobe Lightroom Cloud into a specific album.

## Setup Instructions

### 1. Adobe Developer Console
1.  Go to the [Adobe Developer Console](https://console.adobe.io/).
2.  Create a new project.
3.  Add the **Lightroom Services** API to the project. (Note: In the console, this may be listed under "Photoshop Lightroom" or simply "Lightroom Services").
4.  Configure OAuth2:
    *   Set the "Default redirect URI" to `https://localhost/`.
    *   Set the "Redirect URI pattern" to `https://localhost/.*`.
5.  Note your **Client ID** and **Client Secret**.

### 2. Configuration
1.  Copy `.env.example` to `.env`:
    ```bash
    cp .env.example .env
    ```
2.  Fill in your `ADOBE_CLIENT_ID` and `ADOBE_CLIENT_SECRET` in `.env`.

### 3. Authentication
Since this is a background service, you need to perform a one-time authentication to get a refresh token.

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

## Structure
- `src/monitor.py`: Main logic for file monitoring and triggering uploads.
- `src/lightroom.py`: Wrapper for the Lightroom API.
- `src/auth_helper.py`: Helper script for initial OAuth2 authentication.
- `data/uploaded_files.log`: Keeps track of uploaded files to avoid duplicates.
- `photos/`: The directory to monitor (mapped to `/photos` in the container).
