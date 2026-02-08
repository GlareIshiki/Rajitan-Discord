"""
MemoryManager — 3層記憶の読み書き統合。

Tier 1 (ワーキングメモリ): メモリdict + Redis (TTL: 1時間)
Tier 2 (アクションログ):   Redis (TTL: 6時間)
Tier 3 (永続記憶):         SQLite
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from rajitan.agent.memory.models import (
    ActionLogEntry,
    LongTermMemory,
    PendingAction,
    SessionMemory,
    WorkingMemory,
)
from rajitan.utils.logger import get_logger

logger = get_logger("agent.memory")

# Redis key prefixes
_WM_PREFIX = "agent_wm:"       # Tier 1
_LOG_PREFIX = "agent_log:"     # Tier 2

# TTLs
_WM_TTL = 3600      # 1 hour
_LOG_TTL = 21600     # 6 hours


class MemoryManager:
    """3層記憶の統合管理"""

    def __init__(self, redis_client, db_client):
        self.redis = redis_client
        self.db = db_client
        # Tier 1: メモリキャッシュ（高速パス）
        self._working: Dict[str, WorkingMemory] = {}

    # ─── Tier 1: ワーキングメモリ ───

    async def get_working_memory(self, channel_id: str) -> WorkingMemory:
        """チャンネルのワーキングメモリを取得（なければ空で作成）"""
        # 高速パス: メモリdict
        if channel_id in self._working:
            wm = self._working[channel_id]
            wm._cleanup_expired()
            return wm

        # Redisフォールバック
        try:
            data = await self.redis.get_cache(f"{_WM_PREFIX}{channel_id}")
            if data:
                wm = WorkingMemory.from_dict(data)
                wm._cleanup_expired()
                self._working[channel_id] = wm
                return wm
        except Exception as e:
            logger.warning(f"Failed to read working memory from Redis: {e}")

        # 新規作成
        wm = WorkingMemory(channel_id=channel_id)
        self._working[channel_id] = wm
        return wm

    async def set_pending_action(self, channel_id: str, action: PendingAction):
        """待ちアクションを設定"""
        wm = await self.get_working_memory(channel_id)
        # 同じタイプの既存アクションは上書き
        wm.pending_actions = [
            a for a in wm.pending_actions
            if a.action_type != action.action_type
        ]
        wm.pending_actions.append(action)
        wm.updated_at = datetime.now()
        await self._save_working_memory(wm)

    async def clear_pending_actions(self, channel_id: str):
        """全待ちアクションをクリア"""
        wm = await self.get_working_memory(channel_id)
        wm.pending_actions = []
        wm.updated_at = datetime.now()
        await self._save_working_memory(wm)

    async def has_pending_action(self, channel_id: str) -> bool:
        """待ちアクションがあるか（on_messageで毎回呼ばれるため高速）"""
        # 高速パス: メモリdict
        if channel_id in self._working:
            return self._working[channel_id].has_pending()

        # Redisフォールバック
        try:
            data = await self.redis.get_cache(f"{_WM_PREFIX}{channel_id}")
            if data:
                wm = WorkingMemory.from_dict(data)
                self._working[channel_id] = wm
                return wm.has_pending()
        except Exception as e:
            logger.warning(f"Failed to check pending action: {e}")

        return False

    async def add_context_note(self, channel_id: str, note: str):
        """短いメモを追加（最大5件）"""
        wm = await self.get_working_memory(channel_id)
        wm.context_notes.append(note)
        wm.context_notes = wm.context_notes[-5:]  # 最新5件のみ
        wm.updated_at = datetime.now()
        await self._save_working_memory(wm)

    async def _save_working_memory(self, wm: WorkingMemory):
        """ワーキングメモリをメモリdict + Redisに保存"""
        self._working[wm.channel_id] = wm
        try:
            await self.redis.set_cache(
                f"{_WM_PREFIX}{wm.channel_id}",
                wm.to_dict(),
                ttl=_WM_TTL,
            )
        except Exception as e:
            logger.warning(f"Failed to save working memory to Redis: {e}")

    # ─── Tier 2: アクションログ ───

    async def log_action(self, entry: ActionLogEntry):
        """アクションを記録"""
        session = await self.get_session_memory(entry.channel_id)
        session.actions.append(entry)
        # 最大20件保持
        session.actions = session.actions[-20:]

        try:
            await self.redis.set_cache(
                f"{_LOG_PREFIX}{entry.channel_id}",
                session.to_dict(),
                ttl=_LOG_TTL,
            )
        except Exception as e:
            logger.warning(f"Failed to log action to Redis: {e}")

    async def get_session_memory(self, channel_id: str) -> SessionMemory:
        """チャンネルの今日のアクション履歴を取得"""
        try:
            data = await self.redis.get_cache(f"{_LOG_PREFIX}{channel_id}")
            if data:
                return SessionMemory.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to read session memory from Redis: {e}")

        return SessionMemory(channel_id=channel_id)

    # ─── Tier 3: 永続記憶 ───

    async def remember(self, memory: LongTermMemory):
        """長期記憶に保存（UPSERT）"""
        try:
            await self.db.upsert_agent_memory(
                guild_id=memory.guild_id,
                category=memory.category,
                key=memory.key,
                value=memory.value,
                channel_id=memory.channel_id,
                user_id=memory.user_id,
            )
        except Exception as e:
            logger.error(f"Failed to save long-term memory: {e}")

    async def recall(
        self,
        guild_id: str,
        category: str = None,
        user_id: str = None,
        channel_id: str = None,
        limit: int = 10,
    ) -> List[LongTermMemory]:
        """長期記憶を検索"""
        try:
            rows = await self.db.get_agent_memories(
                guild_id=guild_id,
                category=category,
                user_id=user_id,
                channel_id=channel_id,
                limit=limit,
            )
            return [
                LongTermMemory(
                    guild_id=r["guild_id"],
                    category=r["category"],
                    key=r["key"],
                    value=r["value"],
                    channel_id=r.get("channel_id"),
                    user_id=r.get("user_id"),
                    created_at=(
                        datetime.fromisoformat(r["created_at"])
                        if r.get("created_at")
                        else datetime.now()
                    ),
                    updated_at=(
                        datetime.fromisoformat(r["updated_at"])
                        if r.get("updated_at")
                        else datetime.now()
                    ),
                )
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to recall long-term memory: {e}")
            return []

    async def forget(self, guild_id: str, category: str, key: str) -> bool:
        """長期記憶を削除"""
        try:
            return await self.db.delete_agent_memory(guild_id, category, key)
        except Exception as e:
            logger.error(f"Failed to forget long-term memory: {e}")
            return False
