"""Instagram authentication routes via instagrapi.

No OAuth needed — uses username/password login with session persistence.
Endpoints:
1. POST /login — Log in with IG credentials
2. POST /login/2fa — Submit 2FA verification code
3. GET /status — Check connection status
4. DELETE /disconnect — Remove stored session
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from rajitan.web.auth import get_current_user
from rajitan.web.server import app_state
from rajitan.utils.logger import get_logger

logger = get_logger("instagram_auth")

router = APIRouter(tags=["instagram"])


class LoginRequest(BaseModel):
    username: str
    password: str


class Login2FARequest(BaseModel):
    username: str
    password: str
    verification_code: str


def _get_instagram_client():
    """Get InstagramClient from app_state."""
    client = app_state.get("instagram_client")
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Instagram not configured",
        )
    return client


# ======================================================================
# Endpoints
# ======================================================================


@router.post("/login")
async def instagram_login(body: LoginRequest, user=Depends(get_current_user)):
    """Log in to Instagram with username/password.

    Password is used only for login and NOT stored.
    Only the session token is persisted.
    """
    discord_id = user["id"]
    ig_client = _get_instagram_client()

    result = await ig_client.login(discord_id, body.username, body.password)

    if not result["success"]:
        status_code = status.HTTP_400_BAD_REQUEST
        if result.get("two_factor"):
            status_code = status.HTTP_428_PRECONDITION_REQUIRED
        elif result.get("challenge"):
            status_code = status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=status_code, detail=result["error"])

    logger.info(f"Instagram connected for user {discord_id} ({body.username})")
    return {"connected": True, "username": result["username"]}


@router.post("/login/2fa")
async def instagram_login_2fa(body: Login2FARequest, user=Depends(get_current_user)):
    """Submit 2FA verification code to complete login."""
    discord_id = user["id"]
    ig_client = _get_instagram_client()

    result = await ig_client.login(
        discord_id, body.username, body.password,
        verification_code=body.verification_code,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    logger.info(f"Instagram connected (2FA) for user {discord_id} ({body.username})")
    return {"connected": True, "username": result["username"]}


@router.get("/status")
async def instagram_status(user=Depends(get_current_user)):
    """Check if Instagram is connected."""
    discord_id = user["id"]
    ig_client = _get_instagram_client()

    connected = await ig_client.is_connected(discord_id)
    username = await ig_client.get_ig_username(discord_id) if connected else None

    return {"connected": connected, "username": username}


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def instagram_disconnect(user=Depends(get_current_user)):
    """Disconnect Instagram account."""
    discord_id = user["id"]
    ig_client = _get_instagram_client()
    await ig_client.disconnect(discord_id)
    logger.info(f"Instagram disconnected for user {discord_id}")
