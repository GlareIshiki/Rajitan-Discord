import os
from typing import Optional

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Config:
    """Application configuration"""
    
    def __init__(self):
        # Discord Configuration
        self.discord_bot_token = os.getenv("DISCORD_BOT_TOKEN")
        self.discord_guild_id = os.getenv("DISCORD_GUILD_ID")
        
        # OpenAI Configuration
        self.openai_api_key = os.getenv("OPENAI_API_KEY")

        # DeepSeek Configuration
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        
        # YouTube Data API Configuration
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        
        # Spotify Web API Configuration
        self.spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        
        # Redis Configuration
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_password = os.getenv("REDIS_PASSWORD")
        self.redis_db = int(os.getenv("REDIS_DB", "0"))
        
        # Database Configuration
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///rajitan.db")
        
        # Application Configuration
        self.debug = os.getenv("DEBUG", "False").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.conversation_timeout = int(os.getenv("CONVERSATION_TIMEOUT", "3600"))
        self.summary_interval = int(os.getenv("SUMMARY_INTERVAL", "1800"))
        self.quiz_interval = int(os.getenv("QUIZ_INTERVAL", "3600"))
        self.music_interval = int(os.getenv("MUSIC_INTERVAL", "2700"))

        # Brave Search API Configuration
        self.brave_search_api_key = os.getenv("BRAVE_SEARCH_API_KEY")

        # Google Calendar Configuration
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.google_redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI",
            "https://api.glareishiki.com/api/google/callback",
        )

        # API Server Configuration
        self.api_host = os.getenv("API_HOST", "0.0.0.0")
        self.api_port = int(os.getenv("API_PORT", "8000"))
        self.api_cors_origins = os.getenv("API_CORS_ORIGINS", "http://localhost:3000").split(",")
        self.api_enabled = os.getenv("API_ENABLED", "True").lower() == "true"


# Global config instance
config = Config()


def get_config() -> Config:
    """Get the global configuration instance"""
    return config