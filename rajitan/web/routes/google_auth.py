"""Google OAuth routes for Google Calendar integration.

Handles the OAuth flow:
1. GET /auth?token=<discord_token> — Redirect to Google consent screen
2. GET /callback?code=...&state=... — Exchange code for tokens, close popup
3. GET /status — Check connection status
4. DELETE /disconnect — Remove stored tokens
"""

import secrets
import time
from typing import Dict, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse

from rajitan.web.auth import get_current_user, verify_discord_token
from rajitan.web.server import app_state
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("google_auth")
config = get_config()

router = APIRouter(tags=["google"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

# In-memory state store: {state_string: {"discord_id": str, "created_at": float}}
_pending_states: Dict[str, Dict[str, Any]] = {}
STATE_TTL = 600  # 10 minutes


def _cleanup_expired_states() -> None:
    """Remove expired state entries."""
    now = time.time()
    expired = [k for k, v in _pending_states.items() if now - v["created_at"] > STATE_TTL]
    for k in expired:
        del _pending_states[k]


def _get_google_client():
    """Get GoogleCalendarClient from app_state."""
    client = app_state.get("google_calendar_client")
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar not configured",
        )
    return client


# ======================================================================
# Endpoints
# ======================================================================


@router.get("/auth")
async def google_auth(token: str = Query(..., description="Discord Bearer token")):
    """Initiate Google OAuth flow.

    Accepts Discord token as query param since this is a browser redirect flow
    (cannot send Authorization headers).
    """
    if not config.google_client_id or not config.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar not configured",
        )

    # Verify Discord token to get user identity
    user = await verify_discord_token(token)
    discord_id = user["id"]

    # Generate state and store mapping
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _pending_states[state] = {
        "discord_id": discord_id,
        "created_at": time.time(),
    }

    # Build Google OAuth URL
    params = {
        "client_id": config.google_client_id,
        "redirect_uri": config.google_redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    google_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    return RedirectResponse(url=google_url)


@router.get("/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Google OAuth callback. Exchanges code for tokens and closes popup."""
    # Look up discord_id from state
    _cleanup_expired_states()
    state_data = _pending_states.pop(state, None)
    if not state_data:
        return HTMLResponse(
            content="<html><body><p>認証がタイムアウトしました。ウィンドウを閉じて再試行してください。</p></body></html>",
            status_code=400,
        )

    discord_id = state_data["discord_id"]

    # Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": config.google_client_id,
                    "client_secret": config.google_client_secret,
                    "redirect_uri": config.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

        if resp.status_code != 200:
            logger.error(f"Google token exchange failed: {resp.status_code} {resp.text}")
            return HTMLResponse(
                content="<html><body><p>認証に失敗しました。ウィンドウを閉じて再試行してください。</p></body></html>",
                status_code=400,
            )

        token_data = resp.json()
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        if not refresh_token:
            logger.error("No refresh_token received from Google")
            return HTMLResponse(
                content="<html><body><p>認証に失敗しました（refresh_token未取得）。ウィンドウを閉じて再試行してください。</p></body></html>",
                status_code=400,
            )

        # Get user email
        email = None
        try:
            async with httpx.AsyncClient() as client:
                info_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if info_resp.status_code == 200:
                email = info_resp.json().get("email")
        except Exception:
            pass

        # Save tokens
        google_client = _get_google_client()
        await google_client.save_tokens(
            discord_id=discord_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            email=email,
        )

        logger.info(f"Google Calendar connected for user {discord_id} ({email})")

    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return HTMLResponse(
            content="<html><body><p>エラーが発生しました。ウィンドウを閉じて再試行してください。</p></body></html>",
            status_code=500,
        )

    # Return HTML that notifies the opener and closes the popup
    return HTMLResponse(
        content="""<html><body><script>
if (window.opener) {
    window.opener.postMessage('google-connected', '*');
}
window.close();
</script><p>接続完了。このウィンドウは自動的に閉じます。</p></body></html>"""
    )


@router.get("/status")
async def google_status(user=Depends(get_current_user)):
    """Check if Google Calendar is connected."""
    discord_id = user["id"]
    google_client = _get_google_client()

    connected = await google_client.is_connected(discord_id)
    email = await google_client.get_user_email(discord_id) if connected else None

    return {"connected": connected, "email": email}


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def google_disconnect(user=Depends(get_current_user)):
    """Disconnect Google Calendar."""
    discord_id = user["id"]
    google_client = _get_google_client()
    await google_client.disconnect(discord_id)
    logger.info(f"Google Calendar disconnected for user {discord_id}")
