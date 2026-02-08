import urllib.parse
from typing import Optional, Dict, Any
from rajitan.api.youtube_client import YouTubeClient
from rajitan.api.spotify_client import SpotifyClient
from rajitan.utils.logger import get_logger

logger = get_logger("music_searcher")


class MusicSearcher:
    """Unified music search across YouTube and Spotify with fallback"""

    def __init__(
        self,
        youtube_client: Optional[YouTubeClient] = None,
        spotify_client: Optional[SpotifyClient] = None
    ):
        self.youtube_client = youtube_client
        self.spotify_client = spotify_client

    async def search(self, artist: str, title: str) -> Dict[str, Any]:
        """Search for a song and return the best available result.

        Returns a dict with keys:
            - url: str (direct link or search fallback)
            - source: str ("youtube", "spotify", or "youtube_search")
            - title: str (from API or original)
            - artist: str (from API or original)
        """
        if not artist and not title:
            return self._fallback_result(artist, title)

        # Try YouTube API first
        if self.youtube_client:
            try:
                result = await self.youtube_client.search_by_artist_and_title(artist, title)
                if result:
                    return {
                        "url": result["url"],
                        "source": "youtube",
                        "title": result.get("title", title),
                        "artist": result.get("channel", artist),
                    }
            except Exception as e:
                logger.debug(f"YouTube search failed: {e}")

        # Try Spotify API
        if self.spotify_client:
            try:
                result = await self.spotify_client.search_by_artist_and_title(artist, title)
                if result:
                    return {
                        "url": result["spotify_url"],
                        "source": "spotify",
                        "title": result.get("title", title),
                        "artist": result.get("artist", artist),
                    }
            except Exception as e:
                logger.debug(f"Spotify search failed: {e}")

        # Fallback to YouTube search URL
        return self._fallback_result(artist, title)

    def _fallback_result(self, artist: str, title: str) -> Dict[str, Any]:
        """Generate a YouTube search URL as fallback"""
        query = urllib.parse.quote(f"{artist} {title}".strip())
        return {
            "url": f"https://www.youtube.com/results?search_query={query}",
            "source": "youtube_search",
            "title": title,
            "artist": artist,
        }
