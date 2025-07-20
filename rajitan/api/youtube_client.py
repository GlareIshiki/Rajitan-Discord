import asyncio
import httpx
from typing import Optional, Dict, Any, List
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("youtube_client")
config = get_config()


class YouTubeClient:
    """YouTube Data API client for music search"""
    
    def __init__(self):
        self.api_key = config.youtube_api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.client = httpx.AsyncClient()
    
    async def search_music(self, query: str, max_results: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Search for music videos on YouTube"""
        try:
            if not self.api_key:
                logger.warning("YouTube API key not configured")
                return None
            
            # Search parameters
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "videoCategoryId": "10",  # Music category
                "maxResults": max_results,
                "order": "relevance",
                "key": self.api_key
            }
            
            response = await self.client.get(f"{self.base_url}/search", params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse results
            results = []
            for item in data.get("items", []):
                video_info = {
                    "title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                    "description": item["snippet"]["description"],
                    "video_id": item["id"]["videoId"],
                    "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    "thumbnail": item["snippet"]["thumbnails"]["medium"]["url"]
                }
                results.append(video_info)
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to search YouTube: {e}")
            return None
    
    async def get_video_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a YouTube video"""
        try:
            if not self.api_key:
                logger.warning("YouTube API key not configured")
                return None
            
            params = {
                "part": "snippet,statistics,contentDetails",
                "id": video_id,
                "key": self.api_key
            }
            
            response = await self.client.get(f"{self.base_url}/videos", params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get("items"):
                return None
            
            item = data["items"][0]
            
            video_details = {
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "description": item["snippet"]["description"],
                "duration": item["contentDetails"]["duration"],
                "view_count": item["statistics"].get("viewCount", 0),
                "like_count": item["statistics"].get("likeCount", 0),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": item["snippet"]["thumbnails"]["medium"]["url"]
            }
            
            return video_details
            
        except Exception as e:
            logger.error(f"Failed to get video details: {e}")
            return None
    
    async def search_by_artist_and_title(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """Search for a specific song by artist and title"""
        try:
            query = f"{artist} {title}"
            results = await self.search_music(query, max_results=1)
            
            if results:
                return results[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to search by artist and title: {e}")
            return None
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()