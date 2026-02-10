"""SQLite storage for playlists (halfmaid.db)."""

import aiosqlite
from typing import Optional

from halfmaid.queue.models import Playlist, PlaylistTrack
from halfmaid.utils.logger import get_logger

logger = get_logger("storage.database")

DB_PATH = "halfmaid.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    url TEXT NOT NULL,
    duration_seconds INTEGER DEFAULT 0,
    position INTEGER NOT NULL,
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
);
"""


class PlaylistDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def initialize(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.execute("PRAGMA foreign_keys = ON")
            await db.commit()
        logger.info(f"Playlist database initialized: {self.db_path}")

    async def save_playlist(
        self,
        guild_id: str,
        name: str,
        created_by: str,
        tracks: list[dict],
    ) -> Playlist:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cursor = await db.execute(
                "INSERT INTO playlists (guild_id, name, created_by) VALUES (?, ?, ?)",
                (guild_id, name, created_by),
            )
            playlist_id = cursor.lastrowid

            for i, t in enumerate(tracks):
                await db.execute(
                    "INSERT INTO playlist_tracks (playlist_id, title, artist, url, duration_seconds, position) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (playlist_id, t["title"], t["artist"], t["url"], t.get("duration_seconds", 0), i),
                )

            await db.commit()

        return Playlist(
            id=playlist_id,
            guild_id=guild_id,
            name=name,
            created_by=created_by,
            tracks=[
                PlaylistTrack(
                    title=t["title"],
                    artist=t["artist"],
                    url=t["url"],
                    duration_seconds=t.get("duration_seconds", 0),
                    position=i,
                )
                for i, t in enumerate(tracks)
            ],
        )

    async def list_playlists(self, guild_id: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT p.id, p.name, p.created_by, p.created_at, "
                "(SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = p.id) as track_count "
                "FROM playlists p WHERE p.guild_id = ? ORDER BY p.created_at DESC",
                (guild_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "created_by": row["created_by"],
                    "created_at": row["created_at"],
                    "track_count": row["track_count"],
                }
                for row in rows
            ]

    async def get_playlist(self, playlist_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None

            cursor = await db.execute(
                "SELECT * FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
                (playlist_id,),
            )
            tracks = await cursor.fetchall()

            return {
                "id": row["id"],
                "guild_id": row["guild_id"],
                "name": row["name"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "tracks": [
                    {
                        "title": t["title"],
                        "artist": t["artist"],
                        "url": t["url"],
                        "duration_seconds": t["duration_seconds"],
                        "position": t["position"],
                    }
                    for t in tracks
                ],
            }

    async def delete_playlist(self, playlist_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cursor = await db.execute(
                "DELETE FROM playlists WHERE id = ?", (playlist_id,)
            )
            await db.commit()
            return cursor.rowcount > 0
