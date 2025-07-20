import asyncio
import httpx
import base64
from typing import Optional, Dict, Any, List
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("spotify_client")
config = get_config()


class SpotifyClient:
    """Spotify Web API client for music search and metadata"""
    
    def __init__(self):
        self.client_id = config.spotify_client_id
        self.client_secret = config.spotify_client_secret
        self.base_url = "https://api.spotify.com/v1"
        self.token_url = "https://accounts.spotify.com/api/token"
        self.access_token = None
        self.client = httpx.AsyncClient()
    
    async def _get_access_token(self) -> Optional[str]:
        """Get Spotify access token using client credentials flow"""
        try:
            if not self.client_id or not self.client_secret:
                logger.warning("Spotify client credentials not configured")
                return None
            
            # Encode credentials
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "grant_type": "client_credentials"
            }
            
            response = await self.client.post(self.token_url, headers=headers, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            
            return self.access_token
            
        except Exception as e:
            logger.error(f"Failed to get Spotify access token: {e}")
            return None
    
    async def _get_headers(self) -> Dict[str, str]:
        """Get headers with valid access token"""
        if not self.access_token:
            await self._get_access_token()
        
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    async def search_track(self, query: str, limit: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Search for tracks on Spotify"""
        try:
            headers = await self._get_headers()
            if not headers.get("Authorization"):
                return None
            
            params = {
                "q": query,
                "type": "track",
                "limit": limit,
                "market": "JP"  # Japanese market
            }
            
            response = await self.client.get(f"{self.base_url}/search", headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse results
            results = []
            for item in data.get("tracks", {}).get("items", []):
                track_info = {
                    "title": item["name"],
                    "artist": ", ".join([artist["name"] for artist in item["artists"]]),
                    "album": item["album"]["name"],
                    "duration_ms": item["duration_ms"],
                    "preview_url": item.get("preview_url"),
                    "spotify_url": item["external_urls"]["spotify"],
                    "popularity": item["popularity"],
                    "image_url": item["album"]["images"][0]["url"] if item["album"]["images"] else None
                }
                results.append(track_info)
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to search Spotify tracks: {e}")
            return None
    
    async def get_track_details(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific track"""
        try:
            headers = await self._get_headers()
            if not headers.get("Authorization"):
                return None
            
            response = await self.client.get(f"{self.base_url}/tracks/{track_id}", headers=headers)
            response.raise_for_status()
            
            item = response.json()
            
            track_details = {
                "title": item["name"],
                "artist": ", ".join([artist["name"] for artist in item["artists"]]),
                "album": item["album"]["name"],
                "duration_ms": item["duration_ms"],
                "preview_url": item.get("preview_url"),
                "spotify_url": item["external_urls"]["spotify"],
                "popularity": item["popularity"],
                "image_url": item["album"]["images"][0]["url"] if item["album"]["images"] else None,
                "release_date": item["album"]["release_date"],
                "explicit": item["explicit"]
            }
            
            return track_details
            
        except Exception as e:
            logger.error(f"Failed to get track details: {e}")
            return None
    
    async def search_by_artist_and_title(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """Search for a specific song by artist and title"""
        try:
            query = f"artist:{artist} track:{title}"
            results = await self.search_track(query, limit=1)
            
            if results:
                return results[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to search by artist and title: {e}")
            return None
    
    async def get_audio_features(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get audio features for a track"""
        try:
            headers = await self._get_headers()
            if not headers.get("Authorization"):
                return None
            
            response = await self.client.get(f"{self.base_url}/audio-features/{track_id}", headers=headers)
            response.raise_for_status()
            
            features = response.json()
            
            # Return relevant features
            return {
                "danceability": features.get("danceability"),
                "energy": features.get("energy"),
                "valence": features.get("valence"),  # positivity
                "tempo": features.get("tempo"),
                "loudness": features.get("loudness"),
                "acousticness": features.get("acousticness"),
                "instrumentalness": features.get("instrumentalness")
            }
            
        except Exception as e:
            logger.error(f"Failed to get audio features: {e}")
            return None
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()