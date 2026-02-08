"""Discord OAuth token verification for FastAPI"""
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, Any
from rajitan.utils.logger import get_logger

logger = get_logger("web_auth")

security = HTTPBearer()

# Module-level reference to redis_client, set by server.py on startup
_redis_client = None

DISCORD_API_URL = "https://discord.com/api/v10"
TOKEN_CACHE_TTL = 300  # 5 minutes


def set_redis_client(redis_client):
    """Set the redis client for token caching"""
    global _redis_client
    _redis_client = redis_client


async def verify_discord_token(token: str) -> Dict[str, Any]:
    """Verify Discord access token and return user info"""
    # Check cache first
    if _redis_client:
        try:
            cached = await _redis_client.get_cache(f"discord_token:{token}")
            if cached:
                return cached
        except Exception:
            pass

    # Verify with Discord API
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_URL}/users/@me",
            headers={"Authorization": f"Bearer {token}"},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Discord token",
        )

    user_data = response.json()

    # Cache the result
    if _redis_client:
        try:
            await _redis_client.set_cache(
                f"discord_token:{token}", user_data, ttl=TOKEN_CACHE_TTL
            )
        except Exception:
            pass

    return user_data


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """FastAPI dependency: get authenticated Discord user"""
    try:
        user = await verify_discord_token(credentials.credentials)
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )
