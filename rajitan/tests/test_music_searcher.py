"""Tests for rajitan.features.music.searcher module."""

import pytest
import urllib.parse
from unittest.mock import AsyncMock, MagicMock

from rajitan.features.music.searcher import MusicSearcher


@pytest.fixture
def mock_youtube_client():
    client = MagicMock()
    client.search_by_artist_and_title = AsyncMock(
        return_value={
            "url": "https://www.youtube.com/watch?v=yt123",
            "title": "Lemon",
            "channel": "Kenshi Yonezu",
        }
    )
    return client


@pytest.fixture
def mock_spotify_client():
    client = MagicMock()
    client.search_by_artist_and_title = AsyncMock(
        return_value={
            "spotify_url": "https://open.spotify.com/track/sp456",
            "title": "Lemon",
            "artist": "米津玄師",
        }
    )
    return client


# ---------------------------------------------------------------------------
# MusicSearcher.search
# ---------------------------------------------------------------------------

class TestMusicSearcherSearch:
    @pytest.mark.asyncio
    async def test_search_returns_youtube_result(self, mock_youtube_client):
        searcher = MusicSearcher(youtube_client=mock_youtube_client, spotify_client=None)
        result = await searcher.search("米津玄師", "Lemon")
        assert result["source"] == "youtube"
        assert result["url"] == "https://www.youtube.com/watch?v=yt123"
        assert result["title"] == "Lemon"

    @pytest.mark.asyncio
    async def test_search_returns_spotify_when_youtube_unavailable(self, mock_spotify_client):
        searcher = MusicSearcher(youtube_client=None, spotify_client=mock_spotify_client)
        result = await searcher.search("米津玄師", "Lemon")
        assert result["source"] == "spotify"
        assert result["url"] == "https://open.spotify.com/track/sp456"

    @pytest.mark.asyncio
    async def test_search_fallback_when_no_clients(self):
        searcher = MusicSearcher(youtube_client=None, spotify_client=None)
        result = await searcher.search("米津玄師", "Lemon")
        assert result["source"] == "youtube_search"
        assert "youtube.com/results?search_query=" in result["url"]

    @pytest.mark.asyncio
    async def test_fallback_url_encoding(self):
        searcher = MusicSearcher(youtube_client=None, spotify_client=None)
        result = await searcher.search("米津玄師", "Lemon")
        # The URL should contain the URL-encoded query
        expected_query = urllib.parse.quote("米津玄師 Lemon")
        assert expected_query in result["url"]


class TestMusicSearcherFallback:
    def test_fallback_result_contains_required_keys(self):
        searcher = MusicSearcher()
        result = searcher._fallback_result("Artist", "Title")
        assert "url" in result
        assert "source" in result
        assert "title" in result
        assert "artist" in result
        assert result["source"] == "youtube_search"

    def test_fallback_result_encodes_special_characters(self):
        searcher = MusicSearcher()
        result = searcher._fallback_result("アーティスト", "曲名 feat. ゲスト")
        decoded_query = urllib.parse.unquote(result["url"].split("search_query=")[1])
        assert "アーティスト" in decoded_query
        assert "曲名" in decoded_query
