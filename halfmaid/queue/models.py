from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Track:
    title: str
    artist: str
    url: str  # YouTube URL
    stream_url: str  # Direct audio stream URL from yt-dlp
    duration_seconds: int
    thumbnail: Optional[str] = None
    requester: str = ""
    source: str = "youtube"  # "youtube" | "spotify"
    added_at: datetime = field(default_factory=datetime.now)


@dataclass
class PlaylistTrack:
    title: str
    artist: str
    url: str  # YouTube URL (for re-extraction)
    duration_seconds: int
    position: int


@dataclass
class Playlist:
    guild_id: str
    name: str
    created_by: str
    tracks: list[PlaylistTrack] = field(default_factory=list)
    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
