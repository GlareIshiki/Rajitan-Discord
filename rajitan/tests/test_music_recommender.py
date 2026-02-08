"""Tests for rajitan.features.music.recommender module."""

import pytest
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from rajitan.storage.models import Message, MusicRecommendation
from rajitan.features.music.recommender import MusicRecommender


@pytest.fixture
def recommender(mock_openai_client, mock_character_manager):
    """Create a MusicRecommender with mocked dependencies."""
    return MusicRecommender(
        openai_client=mock_openai_client,
        character_manager=mock_character_manager,
        youtube_client=None,
        spotify_client=None,
    )


@pytest.fixture
def recommender_with_youtube(mock_openai_client, mock_character_manager):
    """Create a MusicRecommender with a mocked YouTube client."""
    youtube = MagicMock()
    youtube.search_by_artist_and_title = AsyncMock(
        return_value={"url": "https://www.youtube.com/watch?v=abc123", "title": "Lemon", "channel": "Kenshi Yonezu"}
    )
    return MusicRecommender(
        openai_client=mock_openai_client,
        character_manager=mock_character_manager,
        youtube_client=youtube,
        spotify_client=None,
    )


# ---------------------------------------------------------------------------
# generate_recommendation
# ---------------------------------------------------------------------------

class TestGenerateRecommendation:
    @pytest.mark.asyncio
    async def test_generate_recommendation_success(self, recommender, sample_messages):
        rec = await recommender.generate_recommendation("guild_001", "chan_001", sample_messages)
        assert rec is not None
        assert isinstance(rec, MusicRecommendation)
        assert rec.title == "Lemon"
        assert rec.artist == "米津玄師"
        assert rec.channel_id == "chan_001"

    @pytest.mark.asyncio
    async def test_generate_recommendation_no_messages(self, recommender):
        rec = await recommender.generate_recommendation("guild_001", "chan_001", [])
        assert rec is None

    @pytest.mark.asyncio
    async def test_generate_recommendation_openai_returns_none(self, recommender, sample_messages):
        recommender.openai_client.generate_music_recommendation = AsyncMock(return_value=None)
        rec = await recommender.generate_recommendation("guild_001", "chan_001", sample_messages)
        assert rec is None

    @pytest.mark.asyncio
    async def test_generate_recommendation_fallback_url_when_no_clients(self, recommender, sample_messages):
        rec = await recommender.generate_recommendation("guild_001", "chan_001", sample_messages)
        assert rec is not None
        assert "youtube.com/results?search_query=" in rec.url


# ---------------------------------------------------------------------------
# _find_music_url
# ---------------------------------------------------------------------------

class TestFindMusicUrl:
    @pytest.mark.asyncio
    async def test_find_url_with_youtube_client(self, recommender_with_youtube):
        url = await recommender_with_youtube._find_music_url({"title": "Lemon", "artist": "米津玄師"})
        assert url == "https://www.youtube.com/watch?v=abc123"

    @pytest.mark.asyncio
    async def test_find_url_without_clients_returns_none(self, recommender):
        url = await recommender._find_music_url({"title": "Lemon", "artist": "米津玄師"})
        assert url is None


# ---------------------------------------------------------------------------
# format_recommendation_for_discord
# ---------------------------------------------------------------------------

class TestFormatRecommendation:
    def test_format_with_youtube_direct_url(self, recommender):
        rec = MusicRecommendation(
            title="Lemon",
            artist="米津玄師",
            url="https://www.youtube.com/watch?v=abc123",
            reason="穏やかな楽曲です。",
            channel_id="chan_001",
        )
        formatted = recommender.format_recommendation_for_discord(rec)
        assert "Lemon" in formatted
        assert "米津玄師" in formatted
        assert "YouTubeで聴く" in formatted

    def test_format_with_search_url(self, recommender):
        search_url = "https://www.youtube.com/results?search_query=test"
        rec = MusicRecommendation(
            title="Test Song",
            artist="Test Artist",
            url=search_url,
            reason="テスト理由",
            channel_id="chan_001",
        )
        formatted = recommender.format_recommendation_for_discord(rec)
        assert "YouTubeで検索" in formatted

    def test_format_with_spotify_url(self, recommender):
        rec = MusicRecommendation(
            title="Track",
            artist="Artist",
            url="https://open.spotify.com/track/abc",
            reason="テスト",
            channel_id="chan_001",
        )
        formatted = recommender.format_recommendation_for_discord(rec)
        assert "Spotifyで聴く" in formatted
