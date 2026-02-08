import asyncio
import urllib.parse
from typing import List, Dict, Any, Optional
from datetime import datetime
from rajitan.storage.models import Message, MusicRecommendation
from rajitan.api.openai_client import OpenAIClient
from rajitan.api.youtube_client import YouTubeClient
from rajitan.api.spotify_client import SpotifyClient
from rajitan.character.manager import CharacterManager
from rajitan.utils.logger import get_logger

logger = get_logger("music_recommender")


class MusicRecommender:
    """Generates music recommendations based on conversation mood"""
    
    def __init__(
        self, 
        openai_client: OpenAIClient, 
        character_manager: CharacterManager,
        youtube_client: Optional[YouTubeClient] = None,
        spotify_client: Optional[SpotifyClient] = None
    ):
        self.openai_client = openai_client
        self.character_manager = character_manager
        self.youtube_client = youtube_client
        self.spotify_client = spotify_client
    
    async def generate_recommendation(
        self, 
        guild_id: str,
        channel_id: str,
        messages: List[Message]
    ) -> Optional[MusicRecommendation]:
        """Generate music recommendation based on conversation"""
        try:
            if not messages:
                logger.warning("No messages to generate music recommendation from")
                return None
            
            # Get character for personalized recommendation
            character = await self.character_manager.get_character(guild_id)
            character_name = character.name if character else "らじたん"
            
            # Generate recommendation using OpenAI
            music_data = await self.openai_client.generate_music_recommendation(messages, character_name)
            
            if not music_data:
                logger.error("Failed to generate music recommendation data")
                return None
            
            # Try to find actual URL if possible
            title = music_data.get("title", "Unknown")
            artist = music_data.get("artist", "Unknown")
            url = await self._find_music_url(music_data)

            # Fallback to YouTube search URL with proper encoding
            if not url:
                search_query = urllib.parse.quote(f"{artist} {title}")
                url = f"https://www.youtube.com/results?search_query={search_query}"

            # Create recommendation object
            recommendation = MusicRecommendation(
                title=title,
                artist=artist,
                url=url,
                reason=music_data.get("reason", "会話の雰囲気にふさわしい楽曲です。"),
                channel_id=channel_id,
                created_at=datetime.now()
            )
            
            logger.info(f"Music recommendation generated for channel {channel_id}: {recommendation.title} by {recommendation.artist}")
            return recommendation
            
        except Exception as e:
            logger.error(f"Failed to generate music recommendation: {e}")
            return None
    
    async def _find_music_url(self, music_data: Dict[str, Any]) -> Optional[str]:
        """Try to find actual URL for the recommended music"""
        try:
            title = music_data.get("title", "")
            artist = music_data.get("artist", "")
            
            if not title or not artist:
                return None
            
            # Try YouTube first
            if self.youtube_client:
                try:
                    youtube_result = await self.youtube_client.search_by_artist_and_title(artist, title)
                    if youtube_result:
                        return youtube_result["url"]
                except Exception as e:
                    logger.debug(f"YouTube search failed: {e}")
            
            # Try Spotify as backup
            if self.spotify_client:
                try:
                    spotify_result = await self.spotify_client.search_by_artist_and_title(artist, title)
                    if spotify_result:
                        return spotify_result["spotify_url"]
                except Exception as e:
                    logger.debug(f"Spotify search failed: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find music URL: {e}")
            return None
    
    async def should_recommend_music(
        self, 
        guild_id: str,
        messages: List[Message], 
        context: Dict[str, Any]
    ) -> bool:
        """Determine if music should be recommended based on character and context"""
        try:
            if not messages or len(messages) < 10:
                return False
            
            # Check character preference for music recommendation
            should_use = await self.character_manager.should_use_feature(
                guild_id, "music", context
            )
            
            if not should_use:
                return False
            
            # Additional checks
            activity_level = context.get("activity", {}).get("activity_level", "inactive")
            sentiment = context.get("sentiment", "neutral")
            topics = context.get("topics", [])
            
            # Don't recommend if conversation is inactive
            if activity_level == "inactive":
                return False
            
            # Higher chance if music is mentioned in conversation
            if "音楽" in topics:
                return True
            
            # Random chance based on sentiment and activity
            if sentiment in ["positive", "excited", "relaxed"] and activity_level in ["medium", "high"]:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check music recommendation need: {e}")
            return False
    
    async def get_music_timing(self, guild_id: str) -> int:
        """Get preferred timing for music recommendation based on character"""
        try:
            timing = await self.character_manager.get_feature_timing(guild_id, "music")
            return timing
            
        except Exception as e:
            logger.error(f"Failed to get music timing: {e}")
            return 45  # Default 45 minutes
    
    def format_recommendation_for_discord(self, recommendation: MusicRecommendation) -> str:
        """Format music recommendation for Discord display"""
        try:
            formatted = f"🎵 **音楽推薦**\n\n"
            formatted += f"**{recommendation.title}**\n"
            formatted += f"アーティスト: {recommendation.artist}\n\n"
            formatted += f"💬 {recommendation.reason}\n\n"

            # Distinguish between direct link and search link
            if "youtube.com/results?" in recommendation.url:
                formatted += f"🔍 [YouTubeで検索]({recommendation.url})"
            elif "spotify.com" in recommendation.url:
                formatted += f"🎧 [Spotifyで聴く]({recommendation.url})"
            elif "youtube.com/watch" in recommendation.url:
                formatted += f"▶️ [YouTubeで聴く]({recommendation.url})"
            else:
                formatted += f"🔗 {recommendation.url}"

            return formatted

        except Exception as e:
            logger.error(f"Failed to format music recommendation: {e}")
            return "音楽推薦の表示にエラーが発生しました。"