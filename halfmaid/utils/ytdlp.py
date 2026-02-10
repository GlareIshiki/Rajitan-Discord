"""yt-dlp wrapper for extracting audio stream URLs without downloading."""

import asyncio
from dataclasses import dataclass
from typing import Optional

import yt_dlp

from halfmaid.utils.logger import get_logger

logger = get_logger("utils.ytdlp")

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "default_search": "ytsearch",
    "socket_timeout": 15,
}

YDL_SEARCH_OPTS = {
    **YDL_OPTS,
    "extract_flat": True,
    "default_search": "ytsearch5",
}


@dataclass
class TrackInfo:
    title: str
    artist: str
    url: str
    stream_url: str
    duration_seconds: int
    thumbnail: Optional[str]


class YtDlpExtractor:
    """Extract audio stream URLs from YouTube via yt-dlp."""

    async def extract(self, query: str) -> Optional[TrackInfo]:
        """Extract a single track's stream URL from a URL or search query."""
        import time
        try:
            t0 = time.monotonic()
            info = await asyncio.to_thread(self._extract_sync, query)
            t1 = time.monotonic()
            logger.info(f"yt-dlp extract '{query}': {t1-t0:.1f}s")
            if not info:
                return None

            # If search returned entries, take first
            if "entries" in info:
                entries = list(info["entries"])
                if not entries:
                    return None
                info = entries[0]
                # Need full extraction for the entry
                if not info.get("url") or info.get("_type") == "url":
                    webpage_url = info.get("url") or info.get("webpage_url", "")
                    if webpage_url:
                        t2 = time.monotonic()
                        info = await asyncio.to_thread(self._extract_sync, webpage_url)
                        t3 = time.monotonic()
                        logger.info(f"yt-dlp re-extract '{webpage_url}': {t3-t2:.1f}s")
                        if not info:
                            return None

            return self._to_track_info(info)
        except Exception as e:
            logger.error(f"yt-dlp extraction failed for '{query}': {e}")
            return None

    async def search(self, query: str, limit: int = 5) -> list[TrackInfo]:
        """Search YouTube and return multiple results."""
        try:
            search_query = f"ytsearch{limit}:{query}"
            info = await asyncio.to_thread(self._extract_sync, search_query)
            if not info or "entries" not in info:
                return []

            results = []
            for entry in info.get("entries", []):
                if not entry:
                    continue
                try:
                    track = self._to_track_info(entry)
                    if track:
                        results.append(track)
                except Exception:
                    continue
            return results
        except Exception as e:
            logger.error(f"yt-dlp search failed for '{query}': {e}")
            return []

    async def refresh_stream_url(self, url: str) -> Optional[str]:
        """Re-extract a fresh stream URL for a given YouTube URL."""
        try:
            info = await asyncio.to_thread(self._extract_sync, url)
            if info:
                return info.get("url")
        except Exception as e:
            logger.error(f"Stream URL refresh failed: {e}")
        return None

    def _extract_sync(self, query: str) -> Optional[dict]:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            return ydl.extract_info(query, download=False)

    def _to_track_info(self, info: dict) -> Optional[TrackInfo]:
        stream_url = info.get("url")
        webpage_url = info.get("webpage_url", "")
        title = info.get("title", "Unknown")
        artist = info.get("uploader", info.get("artist", info.get("channel", "Unknown")))
        duration = int(info.get("duration") or 0)
        thumbnail = info.get("thumbnail")

        if not stream_url and not webpage_url:
            return None

        return TrackInfo(
            title=title,
            artist=artist,
            url=webpage_url or stream_url,
            stream_url=stream_url or "",
            duration_seconds=duration,
            thumbnail=thumbnail,
        )
