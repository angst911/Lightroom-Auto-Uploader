import logging
import secrets
from urllib.parse import urlencode

import requests
from flask import Flask, request, redirect, Response
from markupsafe import escape

logger = logging.getLogger(__name__)

IMS_AUTHORIZE_URL = "https://ims-na1.adobelogin.com/ims/authorize/v2"
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
SCOPES = "lr_partner_apis lr_partner_rendition_apis openid AdobeID offline_access"


def create_app(lr_api, client_id, client_secret, redirect_base_url):
    """lr_api is the same LightroomAPI instance the monitor thread uses, so a
    successful re-auth here takes effect immediately -- no restart required."""
    app = Flask(__name__)
    redirect_uri = redirect_base_url.rstrip("/") + "/auth/callback"
    # Single-user tool; one in-flight OAuth attempt at a time is all we need.
    pending_state = {"value": None}

    @app.route("/")
    def index():
        if lr_api.auth_broken:
            return (
                "<h1>LightroomSync</h1>"
                "<p style='color:#c00'>Authentication is currently broken "
                "(the refresh token has expired or been revoked).</p>"
                "<p><a href='/auth/start'>Click here to re-authenticate</a></p>"
            )
        return "<h1>LightroomSync</h1><p style='color:#080'>Authentication OK.</p>"

    @app.route("/auth/start")
    def auth_start():
        state = secrets.token_urlsafe(24)
        pending_state["value"] = state
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "response_type": "code",
            "state": state,
        }
        return redirect(f"{IMS_AUTHORIZE_URL}?{urlencode(params)}")

    @app.route("/auth/callback")
    def auth_callback():
        error = request.args.get("error")
        if error:
            description = escape(request.args.get("error_description", ""))
            return Response(
                f"<h1>Adobe returned an error</h1><pre>{escape(error)}: {description}</pre>",
                status=400,
            )

        state = request.args.get("state")
        expected_state = pending_state["value"]
        pending_state["value"] = None  # single-use, regardless of outcome
        if not expected_state or state != expected_state:
            return Response(
                "<h1>Invalid or expired login attempt</h1>"
                "<p>Please start over at <a href='/auth/start'>/auth/start</a>.</p>",
                status=400,
            )

        code = request.args.get("code")
        if not code:
            return Response("<h1>No authorization code received</h1>", status=400)

        try:
            resp = requests.post(
                IMS_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=15,
            )
            resp.raise_for_status()
            new_refresh_token = resp.json()["refresh_token"]
        except Exception as e:
            logger.error(f"Failed to exchange auth code for tokens: {e}")
            return Response(
                f"<h1>Failed to complete authentication</h1><pre>{escape(str(e))}</pre>",
                status=500,
            )

        lr_api.update_refresh_token(new_refresh_token)
        logger.info("Re-authentication completed successfully via web flow.")
        return (
            "<h1>Success</h1>"
            "<p>LightroomSync has been re-authenticated. You can close this window.</p>"
        )

    return app


def run_web_server(lr_api, client_id, client_secret, redirect_base_url, port=5000):
    app = create_app(lr_api, client_id, client_secret, redirect_base_url)
    # Flask's built-in server is fine here: low-traffic, single-user, LAN-only admin endpoint.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
