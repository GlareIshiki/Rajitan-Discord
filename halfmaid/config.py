import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class HalfMaidConfig:
    def __init__(self):
        self.discord_token = os.getenv("HALFMAID_DISCORD_TOKEN")
        self.api_host = os.getenv("HALFMAID_API_HOST", "127.0.0.1")
        self.api_port = int(os.getenv("HALFMAID_API_PORT", "8001"))
        self.default_volume = int(os.getenv("HALFMAID_DEFAULT_VOLUME", "50"))
        self.idle_timeout = int(os.getenv("HALFMAID_IDLE_TIMEOUT", "300"))
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        # Spotify (for search → YouTube playback)
        self.spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")


config = HalfMaidConfig()


def get_config() -> HalfMaidConfig:
    return config
