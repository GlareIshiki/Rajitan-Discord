"""Google Calendar API client for fetching events.

Handles OAuth token management (refresh, storage) and event retrieval.
Uses httpx for async HTTP requests and aiosqlite for token persistence.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import aiosqlite
import httpx

from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("google_calendar")
config = get_config()

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

CACHE_TTL_SECONDS = 300  # 5 minutes


class GoogleCalendarClient:
    """Google Calendar API client with token management and caching."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.client = httpx.AsyncClient(timeout=15.0)
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ======================================================================
    # Token management
    # ======================================================================

    async def _get_tokens(self, discord_id: str) -> Optional[Dict[str, str]]:
        """Get stored tokens from SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT access_token, refresh_token, token_expiry, email "
                "FROM google_tokens WHERE discord_id = ?",
                (discord_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "access_token": row["access_token"],
                "refresh_token": row["refresh_token"],
                "token_expiry": row["token_expiry"],
                "email": row["email"],
            }

    async def save_tokens(
        self,
        discord_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        email: Optional[str] = None,
    ) -> None:
        """Save or update Google tokens in SQLite."""
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO google_tokens
                   (discord_id, access_token, refresh_token, token_expiry, email, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(discord_id) DO UPDATE SET
                     access_token = excluded.access_token,
                     refresh_token = excluded.refresh_token,
                     token_expiry = excluded.token_expiry,
                     email = COALESCE(excluded.email, google_tokens.email),
                     updated_at = CURRENT_TIMESTAMP""",
                (discord_id, access_token, refresh_token, expiry, email),
            )
            await db.commit()

    async def _refresh_access_token(
        self, discord_id: str, refresh_token: str
    ) -> Optional[str]:
        """Refresh the access token using the refresh token."""
        try:
            resp = await self.client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": config.google_client_id,
                    "client_secret": config.google_client_secret,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Google token refresh failed ({resp.status_code}): {resp.text}"
                )
                # Token revoked or invalid — clean up
                await self.disconnect(discord_id)
                return None

            data = resp.json()
            new_access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)

            # Update stored access token (refresh_token stays the same)
            expiry = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE google_tokens SET access_token = ?, token_expiry = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (new_access_token, expiry, discord_id),
                )
                await db.commit()

            return new_access_token
        except Exception as e:
            logger.error(f"Failed to refresh Google token: {e}")
            return None

    async def _get_valid_access_token(self, discord_id: str) -> Optional[str]:
        """Get a valid access token, refreshing if expired."""
        tokens = await self._get_tokens(discord_id)
        if not tokens:
            return None

        # Check if token is still valid (with 5-minute buffer)
        if tokens["token_expiry"]:
            try:
                expiry = datetime.fromisoformat(tokens["token_expiry"])
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < expiry - timedelta(minutes=5):
                    return tokens["access_token"]
            except (ValueError, TypeError):
                pass

        # Token expired or expiry unknown — refresh
        return await self._refresh_access_token(
            discord_id, tokens["refresh_token"]
        )

    # ======================================================================
    # Event fetching
    # ======================================================================

    def _parse_google_event(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a Google Calendar event to our unified format."""
        start = item.get("start", {})
        end = item.get("end", {})

        is_all_day = "date" in start
        start_time = start.get("dateTime") or f"{start.get('date')}T00:00:00"
        end_time = end.get("dateTime") or (
            f"{end.get('date')}T00:00:00" if end.get("date") else None
        )

        return {
            "id": item["id"],
            "summary": item.get("summary", "(無題)"),
            "description": item.get("description", ""),
            "start_time": start_time,
            "end_time": end_time,
            "is_all_day": is_all_day,
        }

    async def get_events(
        self,
        discord_id: str,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch events from Google Calendar API."""
        # Check cache
        cache_key = f"{discord_id}:{time_min}:{time_max}"
        cached = self._cache.get(cache_key)
        if cached:
            elapsed = (datetime.now() - cached["fetched_at"]).total_seconds()
            if elapsed < CACHE_TTL_SECONDS:
                return cached["events"]

        access_token = await self._get_valid_access_token(discord_id)
        if not access_token:
            return []

        try:
            params: Dict[str, Any] = {
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if time_min:
                # Ensure timezone suffix
                if not time_min.endswith("Z") and "+" not in time_min:
                    params["timeMin"] = time_min + "+09:00"
                else:
                    params["timeMin"] = time_min
            if time_max:
                if not time_max.endswith("Z") and "+" not in time_max:
                    params["timeMax"] = time_max + "+09:00"
                else:
                    params["timeMax"] = time_max

            resp = await self.client.get(
                f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if resp.status_code == 401:
                # Token may have been revoked
                logger.warning("Google Calendar API returned 401, clearing tokens")
                await self.disconnect(discord_id)
                return []

            if resp.status_code != 200:
                logger.warning(
                    f"Google Calendar API error ({resp.status_code}): {resp.text}"
                )
                return []

            data = resp.json()
            events = [
                self._parse_google_event(item)
                for item in data.get("items", [])
                if item.get("status") != "cancelled"
            ]

            # Cache the result
            self._cache[cache_key] = {
                "events": events,
                "fetched_at": datetime.now(),
            }

            return events
        except Exception as e:
            logger.error(f"Failed to fetch Google Calendar events: {e}")
            return []

    # ======================================================================
    # Connection management
    # ======================================================================

    async def is_connected(self, discord_id: str) -> bool:
        """Check if user has stored Google tokens."""
        tokens = await self._get_tokens(discord_id)
        return tokens is not None

    async def get_user_email(self, discord_id: str) -> Optional[str]:
        """Get the stored Google email for display."""
        tokens = await self._get_tokens(discord_id)
        if tokens:
            return tokens.get("email")
        return None

    async def disconnect(self, discord_id: str) -> bool:
        """Remove stored tokens for a user."""
        # Clear cache entries for this user
        keys_to_remove = [k for k in self._cache if k.startswith(f"{discord_id}:")]
        for k in keys_to_remove:
            del self._cache[k]

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM google_tokens WHERE discord_id = ?",
                (discord_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
