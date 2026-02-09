"""Canva Connect API client for design creation and export.

Handles OAuth token management (refresh, storage) and design workflows.
Uses httpx for async HTTP requests and aiosqlite for token persistence.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiosqlite
import httpx

from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("canva")
config = get_config()

CANVA_API_BASE = "https://api.canva.com/rest/v1"
CANVA_AUTH_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"

EXPORT_POLL_INTERVAL = 2  # seconds
EXPORT_POLL_MAX = 30  # max attempts


class CanvaClient:
    """Canva Connect API client with token management."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.client = httpx.AsyncClient(timeout=60.0)

    # ======================================================================
    # Token management
    # ======================================================================

    async def _get_tokens(self, discord_id: str) -> Optional[Dict[str, str]]:
        """Get stored Canva tokens from SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT access_token, refresh_token, token_expiry "
                "FROM canva_tokens WHERE discord_id = ?",
                (discord_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "access_token": row["access_token"],
                "refresh_token": row["refresh_token"],
                "token_expiry": row["token_expiry"],
            }

    async def save_tokens(
        self,
        discord_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> None:
        """Save or update Canva tokens in SQLite."""
        expiry = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO canva_tokens
                   (discord_id, access_token, refresh_token, token_expiry, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(discord_id) DO UPDATE SET
                     access_token = excluded.access_token,
                     refresh_token = excluded.refresh_token,
                     token_expiry = excluded.token_expiry,
                     updated_at = CURRENT_TIMESTAMP""",
                (discord_id, access_token, refresh_token, expiry),
            )
            await db.commit()

    async def _refresh_access_token(
        self, discord_id: str, refresh_token: str
    ) -> Optional[str]:
        """Refresh the access token using the refresh token."""
        try:
            resp = await self.client.post(
                CANVA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": config.canva_client_id,
                    "client_secret": config.canva_client_secret,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Canva token refresh failed ({resp.status_code}): {resp.text}"
                )
                await self.disconnect(discord_id)
                return None

            data = resp.json()
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", refresh_token)
            expires_in = data.get("expires_in", 3600)
            await self.save_tokens(discord_id, new_access, new_refresh, expires_in)
            return new_access
        except Exception as e:
            logger.error(f"Failed to refresh Canva token: {e}")
            return None

    async def _get_valid_access_token(self, discord_id: str) -> Optional[str]:
        """Get a valid access token, refreshing if expired."""
        tokens = await self._get_tokens(discord_id)
        if not tokens:
            return None

        if tokens["token_expiry"]:
            try:
                expiry = datetime.fromisoformat(tokens["token_expiry"])
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < expiry - timedelta(minutes=5):
                    return tokens["access_token"]
            except (ValueError, TypeError):
                pass

        return await self._refresh_access_token(
            discord_id, tokens["refresh_token"]
        )

    # ======================================================================
    # Design operations
    # ======================================================================

    async def create_design(
        self,
        discord_id: str,
        template_id: str,
        text_replacements: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Create a design from a Canva template via autofill.

        Returns design_id on success, None on failure.
        """
        access_token = await self._get_valid_access_token(discord_id)
        if not access_token:
            return None

        body: Dict[str, Any] = {"brand_template_id": template_id}
        if text_replacements:
            body["data"] = {
                k: {"type": "text", "text": v}
                for k, v in text_replacements.items()
            }

        try:
            resp = await self.client.post(
                f"{CANVA_API_BASE}/autofills",
                json=body,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Canva create design failed ({resp.status_code}): {resp.text}")
                return None

            data = resp.json()
            job = data.get("job", {})

            # Poll for completion if status is not done
            job_id = job.get("id")
            if job.get("status") != "completed" and job_id:
                design_id = await self._poll_autofill_job(discord_id, job_id, access_token)
                return design_id

            result = job.get("result", {})
            return result.get("design", {}).get("id")
        except Exception as e:
            logger.error(f"Canva create design error: {e}")
            return None

    async def _poll_autofill_job(
        self, discord_id: str, job_id: str, access_token: str
    ) -> Optional[str]:
        """Poll autofill job until completed."""
        for _ in range(EXPORT_POLL_MAX):
            await asyncio.sleep(EXPORT_POLL_INTERVAL)
            try:
                resp = await self.client.get(
                    f"{CANVA_API_BASE}/autofills/{job_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                job = data.get("job", {})
                if job.get("status") == "completed":
                    return job.get("result", {}).get("design", {}).get("id")
                if job.get("status") == "failed":
                    logger.error(f"Canva autofill job failed: {job}")
                    return None
            except Exception as e:
                logger.warning(f"Canva poll error: {e}")
        logger.error("Canva autofill job timed out")
        return None

    async def export_design(
        self, discord_id: str, design_id: str, fmt: str = "png"
    ) -> Optional[str]:
        """Export a design to an image URL.

        Returns the download URL (valid for 24h), or None on failure.
        """
        access_token = await self._get_valid_access_token(discord_id)
        if not access_token:
            return None

        try:
            resp = await self.client.post(
                f"{CANVA_API_BASE}/design-export-requests",
                json={"design_id": design_id, "format": {"type": fmt}},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Canva export request failed ({resp.status_code}): {resp.text}")
                return None

            data = resp.json()
            job = data.get("job", {})
            job_id = job.get("id")

            if job.get("status") == "completed":
                urls = job.get("result", {}).get("urls", [])
                return urls[0] if urls else None

            # Poll for export completion
            if job_id:
                return await self._poll_export_job(job_id, access_token)
            return None
        except Exception as e:
            logger.error(f"Canva export error: {e}")
            return None

    async def _poll_export_job(
        self, job_id: str, access_token: str
    ) -> Optional[str]:
        """Poll export job until completed."""
        for _ in range(EXPORT_POLL_MAX):
            await asyncio.sleep(EXPORT_POLL_INTERVAL)
            try:
                resp = await self.client.get(
                    f"{CANVA_API_BASE}/design-export-requests/{job_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                job = data.get("job", {})
                if job.get("status") == "completed":
                    urls = job.get("result", {}).get("urls", [])
                    return urls[0] if urls else None
                if job.get("status") == "failed":
                    logger.error(f"Canva export job failed: {job}")
                    return None
            except Exception as e:
                logger.warning(f"Canva export poll error: {e}")
        logger.error("Canva export job timed out")
        return None

    async def create_and_export(
        self,
        discord_id: str,
        template_id: str,
        text_replacements: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Create a design from template and export to image URL.

        Convenience method combining create_design + export_design.
        Returns the image download URL, or None.
        """
        design_id = await self.create_design(discord_id, template_id, text_replacements)
        if not design_id:
            return None
        return await self.export_design(discord_id, design_id)

    # ======================================================================
    # Connection management
    # ======================================================================

    async def is_connected(self, discord_id: str) -> bool:
        """Check if user has stored Canva tokens."""
        tokens = await self._get_tokens(discord_id)
        return tokens is not None

    async def disconnect(self, discord_id: str) -> bool:
        """Remove stored tokens for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM canva_tokens WHERE discord_id = ?",
                (discord_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
