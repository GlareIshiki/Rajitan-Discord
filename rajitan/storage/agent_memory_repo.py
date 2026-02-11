"""AgentMemoryRepo — Tier 3 (long-term) agent memory DB operations."""

import aiosqlite
from typing import Any, Dict, List, Optional

from rajitan.utils.logger import get_logger

logger = get_logger("agent_memory_repo")


class AgentMemoryRepo:
    """Handles all agent_memories table operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def upsert(
        self, guild_id: str, category: str, key: str, value: str,
        channel_id: str = None, user_id: str = None
    ) -> bool:
        """Insert or update an agent memory entry."""
        try:
            channel_id = channel_id or ''
            user_id = user_id or ''
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO agent_memories
                       (guild_id, channel_id, user_id, category, key, value, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(guild_id, channel_id, user_id, category, key)
                       DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP''',
                    (guild_id, channel_id, user_id, category, key, value)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to upsert agent memory: {e}")
            return False

    async def get_memories(
        self, guild_id: str, category: str = None, user_id: str = None,
        channel_id: str = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get agent memories with optional filters."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                query = "SELECT guild_id, channel_id, user_id, category, key, value, created_at, updated_at FROM agent_memories WHERE guild_id = ?"
                params: list = [guild_id]

                if category:
                    query += " AND category = ?"
                    params.append(category)
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                if channel_id:
                    query += " AND channel_id = ?"
                    params.append(channel_id)

                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                async with db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()
                    return [
                        {
                            "guild_id": r[0],
                            "channel_id": r[1],
                            "user_id": r[2],
                            "category": r[3],
                            "key": r[4],
                            "value": r[5],
                            "created_at": r[6],
                            "updated_at": r[7],
                        }
                        for r in rows
                    ]
        except Exception as e:
            logger.error(f"Failed to get agent memories: {e}")
            return []

    async def delete(self, guild_id: str, category: str, key: str) -> bool:
        """Delete an agent memory entry."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "DELETE FROM agent_memories WHERE guild_id = ? AND category = ? AND key = ?",
                    (guild_id, category, key)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete agent memory: {e}")
            return False
