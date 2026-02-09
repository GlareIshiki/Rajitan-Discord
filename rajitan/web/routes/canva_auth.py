"""Canva OAuth routes for Canva Connect API integration.

Handles the OAuth flow:
1. GET /auth?token=<discord_token> — Redirect to Canva consent screen
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

logger = get_logger("canva_auth")
config = get_config()

router = APIRouter(tags=["canva"])

CANVA_AUTH_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_SCOPE = "design:content:read design:content:write"

# In-memory state store
_pending_states: Dict[str, Dict[str, Any]] = {}
STATE_TTL = 600  # 10 minutes


def _cleanup_expired_states() -> None:
    """Remove expired state entries."""
    now = time.time()
    expired = [k for k, v in _pending_states.items() if now - v["created_at"] > STATE_TTL]
    for k in expired:
        del _pending_states[k]


def _get_canva_client():
    """Get CanvaClient from app_state."""
    client = app_state.get("canva_client")
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canva not configured",
        )
    return client


# ======================================================================
# Endpoints
# ======================================================================


@router.get("/auth")
async def canva_auth(token: str = Query(..., description="Discord Bearer token")):
    """Initiate Canva OAuth flow."""
    if not config.canva_client_id or not config.canva_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canva not configured",
        )

    user = await verify_discord_token(token)
    discord_id = user["id"]

    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _pending_states[state] = {
        "discord_id": discord_id,
        "created_at": time.time(),
    }

    params = {
        "client_id": config.canva_client_id,
        "redirect_uri": config.canva_redirect_uri,
        "response_type": "code",
        "scope": CANVA_SCOPE,
        "state": state,
    }
    canva_url = f"{CANVA_AUTH_URL}?{urlencode(params)}"

    return RedirectResponse(url=canva_url)


@router.get("/callback")
async def canva_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Canva OAuth callback. Exchanges code for tokens and closes popup."""
    _cleanup_expired_states()
    state_data = _pending_states.pop(state, None)
    if not state_data:
        return HTMLResponse(
            content="<html><body><p>認証がタイムアウトしました。ウィンドウを閉じて再試行してください。</p></body></html>",
            status_code=400,
        )

    discord_id = state_data["discord_id"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                CANVA_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": config.canva_client_id,
                    "client_secret": config.canva_client_secret,
                    "redirect_uri": config.canva_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

        if resp.status_code != 200:
            logger.error(f"Canva token exchange failed: {resp.status_code} {resp.text}")
            return HTMLResponse(
                content="<html><body><p>認証に失敗しました。ウィンドウを閉じて再試行してください。</p></body></html>",
                status_code=400,
            )

        token_data = resp.json()
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)

        canva_client = _get_canva_client()
        await canva_client.save_tokens(
            discord_id=discord_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        logger.info(f"Canva connected for user {discord_id}")

    except Exception as e:
        logger.error(f"Canva OAuth callback error: {e}")
        return HTMLResponse(
            content="<html><body><p>エラーが発生しました。ウィンドウを閉じて再試行してください。</p></body></html>",
            status_code=500,
        )

    return HTMLResponse(
        content="""<html><body><script>
if (window.opener) {
    window.opener.postMessage('canva-connected', '*');
}
window.close();
</script><p>接続完了。このウィンドウは自動的に閉じます。</p></body></html>"""
    )


@router.get("/status")
async def canva_status(user=Depends(get_current_user)):
    """Check if Canva is connected."""
    discord_id = user["id"]
    canva_client = _get_canva_client()
    connected = await canva_client.is_connected(discord_id)
    return {"connected": connected}


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def canva_disconnect(user=Depends(get_current_user)):
    """Disconnect Canva account."""
    discord_id = user["id"]
    canva_client = _get_canva_client()
    await canva_client.disconnect(discord_id)
    logger.info(f"Canva disconnected for user {discord_id}")
