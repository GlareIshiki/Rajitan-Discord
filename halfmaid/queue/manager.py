"""In-memory queue manager with per-guild state."""

import random
from dataclasses import dataclass, field
from typing import Optional

from halfmaid.queue.models import Track
from halfmaid.utils.logger import get_logger

logger = get_logger("queue.manager")


@dataclass
class GuildQueue:
    tracks: list[Track] = field(default_factory=list)
    history: list[Track] = field(default_factory=list)
    loop_mode: str = "off"  # "off" | "track" | "queue"
    shuffle: bool = False
    volume: int = 50  # 0-100

    def add(self, track: Track) -> int:
        """Add track to queue. Returns position."""
        self.tracks.append(track)
        return len(self.tracks) - 1

    def remove(self, index: int) -> Optional[Track]:
        """Remove track at index. Returns removed track or None."""
        if 0 <= index < len(self.tracks):
            return self.tracks.pop(index)
        return None

    def clear(self) -> int:
        """Clear queue. Returns number of removed tracks."""
        count = len(self.tracks)
        self.tracks.clear()
        return count

    def next(self, current_track: Optional[Track] = None) -> Optional[Track]:
        """Get next track respecting loop/shuffle settings."""
        if self.loop_mode == "track" and current_track:
            return current_track

        if current_track and self.loop_mode == "queue":
            self.tracks.append(current_track)

        if not self.tracks:
            return None

        if self.shuffle:
            index = random.randrange(len(self.tracks))
            return self.tracks.pop(index)

        return self.tracks.pop(0)

    def move(self, from_idx: int, to_idx: int) -> bool:
        """Move track from one position to another."""
        if not (0 <= from_idx < len(self.tracks) and 0 <= to_idx < len(self.tracks)):
            return False
        track = self.tracks.pop(from_idx)
        self.tracks.insert(to_idx, track)
        return True


class QueueManager:
    """Manages per-guild playback queues."""

    def __init__(self, default_volume: int = 50):
        self._queues: dict[str, GuildQueue] = {}
        self._default_volume = default_volume

    def get(self, guild_id: str) -> GuildQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = GuildQueue(volume=self._default_volume)
        return self._queues[guild_id]

    def remove_guild(self, guild_id: str) -> None:
        self._queues.pop(guild_id, None)

    def get_queue_info(self, guild_id: str) -> dict:
        q = self.get(guild_id)
        return {
            "queue": [
                {
                    "index": i,
                    "title": t.title,
                    "artist": t.artist,
                    "url": t.url,
                    "duration_seconds": t.duration_seconds,
                    "requester": t.requester,
                }
                for i, t in enumerate(q.tracks)
            ],
            "total_duration_seconds": sum(t.duration_seconds for t in q.tracks),
            "loop_mode": q.loop_mode,
            "shuffle": q.shuffle,
        }
