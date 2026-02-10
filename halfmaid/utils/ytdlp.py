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
    "default_search": "ytsearch10",
    "socket_timeout": 15,
}

YDL_SEARCH_OPTS = {
    **YDL_OPTS,
    "extract_flat": True,
    "default_search": "ytsearch10",
}

YDL_RELATED_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "socket_timeout": 15,
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

            # If search returned entries, take first valid one
            if "entries" in info:
                entries = list(info["entries"])
                if not entries:
                    return None
                # Try entries in order until one works
                for entry in entries:
                    if not entry:
                        continue
                    info = entry
                    if not info.get("url") or info.get("_type") == "url":
                        webpage_url = info.get("url") or info.get("webpage_url", "")
                        if webpage_url:
                            t2 = time.monotonic()
                            info = await asyncio.to_thread(self._extract_sync, webpage_url)
                            t3 = time.monotonic()
                            logger.info(f"yt-dlp re-extract '{webpage_url}': {t3-t2:.1f}s")
                    if info and (info.get("url") or info.get("webpage_url")):
                        break
                else:
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

    async def get_related(self, url: str, limit: int = 5, exclude_urls: set = None) -> list[TrackInfo]:
        """Get related videos from a YouTube URL for autoplay."""
        try:
            info = await asyncio.to_thread(self._extract_related_sync, url)
            if not info:
                return []

            # YouTube returns related videos in different fields
            related_entries = []
            # Try 'related_videos' first (some yt-dlp versions)
            for rv in info.get("related_videos", []):
                if rv and rv.get("id"):
                    related_entries.append(rv)
            # Also check 'entries' if this is a playlist/mix result
            for entry in info.get("entries", []):
                if entry:
                    related_entries.append(entry)

            exclude = exclude_urls or set()
            results = []
            for entry in related_entries:
                entry_url = entry.get("webpage_url") or entry.get("url", "")
                if not entry_url or entry_url in exclude:
                    continue
                try:
                    track = self._to_track_info(entry)
                    if track:
                        results.append(track)
                        if len(results) >= limit:
                            break
                except Exception:
                    continue

            logger.info(f"get_related '{url}': found {len(results)} tracks")
            return results
        except Exception as e:
            logger.error(f"get_related failed for '{url}': {e}")
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

    def _extract_related_sync(self, url: str) -> Optional[dict]:
        with yt_dlp.YoutubeDL(YDL_RELATED_OPTS) as ydl:
            return ydl.extract_info(url, download=False)

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
