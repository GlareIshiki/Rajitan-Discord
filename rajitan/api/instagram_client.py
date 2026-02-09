"""Instagram client using instagrapi for photo publishing.

Handles session persistence (SQLite), async wrapping of the sync instagrapi
library, and image download/upload workflows.
"""

import asyncio
import io
import json
import tempfile
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite
import httpx
from instagrapi import Client as InstaClient
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    LoginRequired,
    TwoFactorRequired,
)

from rajitan.utils.logger import get_logger

logger = get_logger("instagram")


class InstagramClient:
    """Instagram API client via instagrapi with session persistence."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._clients: Dict[str, InstaClient] = {}  # discord_id -> InstaClient
        self._http = httpx.AsyncClient(timeout=30.0)

    # ======================================================================
    # Internal helpers
    # ======================================================================

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous instagrapi call in a thread executor."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, partial(func, *args, **kwargs))

    # ======================================================================
    # Session management
    # ======================================================================

    async def login(
        self,
        discord_id: str,
        ig_username: str,
        ig_password: str,
        verification_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log in to Instagram and persist session.

        Returns:
            {"success": True, "username": str} on success
            {"success": False, "error": str, "challenge": bool, "two_factor": bool}
        """
        cl = InstaClient()
        cl.delay_range = [1, 3]  # Anti-ban: random delay between requests

        try:
            if verification_code:
                await self._run_sync(
                    cl.login, ig_username, ig_password,
                    verification_code=verification_code,
                )
            else:
                await self._run_sync(cl.login, ig_username, ig_password)
        except TwoFactorRequired:
            return {
                "success": False,
                "error": "2FA認証コードが必要です",
                "two_factor": True,
                "challenge": False,
            }
        except ChallengeRequired:
            return {
                "success": False,
                "error": "Instagramのセキュリティチャレンジが必要です。Instagramアプリで確認してください",
                "two_factor": False,
                "challenge": True,
            }
        except BadPassword:
            return {
                "success": False,
                "error": "パスワードが正しくありません",
                "two_factor": False,
                "challenge": False,
            }
        except Exception as e:
            logger.error(f"Instagram login failed for {ig_username}: {e}")
            return {
                "success": False,
                "error": f"ログイン失敗: {e}",
                "two_factor": False,
                "challenge": False,
            }

        # Save session
        session_data = await self._run_sync(cl.get_settings)
        await self._save_session(discord_id, ig_username, json.dumps(session_data))
        self._clients[discord_id] = cl

        logger.info(f"Instagram login successful: {ig_username} (discord:{discord_id})")
        return {"success": True, "username": ig_username}

    async def _save_session(
        self, discord_id: str, ig_username: str, session_json: str
    ) -> None:
        """Persist session JSON to SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO instagram_sessions
                   (discord_id, ig_username, session_data, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(discord_id) DO UPDATE SET
                     ig_username = excluded.ig_username,
                     session_data = excluded.session_data,
                     updated_at = CURRENT_TIMESTAMP""",
                (discord_id, ig_username, session_json),
            )
            await db.commit()

    async def _load_session(self, discord_id: str) -> Optional[InstaClient]:
        """Restore an instagrapi Client from stored session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT ig_username, session_data FROM instagram_sessions "
                "WHERE discord_id = ?",
                (discord_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

        cl = InstaClient()
        cl.delay_range = [1, 3]

        try:
            settings = json.loads(row["session_data"])
            await self._run_sync(cl.set_settings, settings)
            # Validate session by fetching timeline
            await self._run_sync(cl.get_timeline_feed)
            self._clients[discord_id] = cl
            logger.info(f"Instagram session restored for {row['ig_username']}")
            return cl
        except (LoginRequired, Exception) as e:
            logger.warning(f"Instagram session expired for discord:{discord_id}: {e}")
            return None

    async def _get_client(self, discord_id: str) -> Optional[InstaClient]:
        """Get a valid instagrapi Client (from cache or DB)."""
        if discord_id in self._clients:
            return self._clients[discord_id]
        return await self._load_session(discord_id)

    # ======================================================================
    # Publishing
    # ======================================================================

    async def post_photo(
        self, discord_id: str, image_path: Path, caption: str
    ) -> Dict[str, Any]:
        """Upload a photo to Instagram feed.

        Args:
            discord_id: Discord user ID
            image_path: Local path to the image file
            caption: Post caption text

        Returns:
            {"success": True, "media_id": str, "media_url": str} or error dict
        """
        cl = await self._get_client(discord_id)
        if not cl:
            return {"success": False, "error": "Instagramに接続されていません。先にログインしてください"}

        try:
            media = await self._run_sync(
                cl.photo_upload, image_path, caption
            )
            # Update session after successful action
            session_data = await self._run_sync(cl.get_settings)
            await self._save_session(
                discord_id,
                cl.username or "",
                json.dumps(session_data),
            )

            media_url = f"https://www.instagram.com/p/{media.code}/"
            logger.info(f"Instagram post successful: {media_url}")
            return {
                "success": True,
                "media_id": media.id,
                "media_url": media_url,
            }
        except LoginRequired:
            # Session expired during action
            self._clients.pop(discord_id, None)
            return {"success": False, "error": "セッションが期限切れです。再ログインしてください"}
        except Exception as e:
            logger.error(f"Instagram post failed: {e}")
            return {"success": False, "error": f"投稿失敗: {e}"}

    async def download_and_post(
        self, discord_id: str, image_url: str, caption: str
    ) -> Dict[str, Any]:
        """Download an image from URL (or local path) and post to Instagram.

        Handles Discord attachment URLs, AI-generated image URLs, Canva exports,
        and local file paths (from generate_image tool).
        Converts PNG to JPEG if needed (instagrapi prefers JPEG).
        """
        # Handle local file paths (e.g. from generate_image tool)
        local_path = Path(image_url) if not image_url.startswith(("http://", "https://")) else None
        if local_path and local_path.exists():
            image_bytes = local_path.read_bytes()
            is_png = local_path.suffix.lower() == ".png"
        else:
            try:
                resp = await self._http.get(image_url)
                resp.raise_for_status()
            except Exception as e:
                return {"success": False, "error": f"画像のダウンロード失敗: {e}"}
            image_bytes = resp.content
            content_type = resp.headers.get("content-type", "")
            is_png = "png" in content_type or image_url.lower().endswith(".png")

        # Convert PNG to JPEG if necessary
        if is_png:
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(image_bytes))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                image_bytes = buf.getvalue()
            except Exception as e:
                logger.warning(f"PNG to JPEG conversion failed, using original: {e}")

        suffix = ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(image_bytes)
            tmp_path = Path(f.name)

        try:
            return await self.post_photo(discord_id, tmp_path, caption)
        finally:
            tmp_path.unlink(missing_ok=True)

    # ======================================================================
    # Connection management
    # ======================================================================

    async def is_connected(self, discord_id: str) -> bool:
        """Check if user has a stored Instagram session."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM instagram_sessions WHERE discord_id = ?",
                (discord_id,),
            )
            return await cursor.fetchone() is not None

    async def get_ig_username(self, discord_id: str) -> Optional[str]:
        """Get the stored Instagram username."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT ig_username FROM instagram_sessions WHERE discord_id = ?",
                (discord_id,),
            )
            row = await cursor.fetchone()
            return row["ig_username"] if row else None

    async def disconnect(self, discord_id: str) -> bool:
        """Remove stored session for a user."""
        self._clients.pop(discord_id, None)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM instagram_sessions WHERE discord_id = ?",
                (discord_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def close(self):
        """Clean up resources."""
        await self._http.aclose()
        self._clients.clear()
