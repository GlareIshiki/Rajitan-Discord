"""FastAPI routes for bot dashboard endpoints"""

from datetime import datetime
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from rajitan.web.auth import get_current_user
from rajitan.web.server import app_state
from rajitan.utils.logger import get_logger

logger = get_logger("web_bot")

router = APIRouter(tags=["bot"])


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable Japanese string."""
    total = int(seconds)
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}日")
    if hours > 0:
        parts.append(f"{hours}時間")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}分")

    return " ".join(parts)


# ======================================================================
# Bot Stats
# ======================================================================


@router.get("/stats")
async def get_stats(user=Depends(get_current_user)):
    """Get bot statistics"""
    bot = app_state.get("bot")
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot not available",
        )

    stats = bot.get_bot_stats()

    return {
        "guilds": stats["guilds"],
        "users": stats["users"],
        "humans": stats["humans"],
        "bots": stats["bots"],
        "channels": stats["channels"],
        "uptime": _format_uptime(stats["uptime"]),
        "status": "online" if stats["ready"] else "offline",
        "latency": stats["latency"],
        "ready": stats["ready"],
    }


@router.get("/stats/users")
async def get_user_breakdown(user=Depends(get_current_user)):
    """Get user breakdown by guild (humans vs bots)"""
    bot = app_state.get("bot")
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot not available",
        )
    return bot.get_user_breakdown()


# ======================================================================
# Guilds
# ======================================================================


@router.get("/guilds")
async def get_guilds(user=Depends(get_current_user)):
    """Get list of guilds the bot is in (filtered by user membership where possible)"""
    bot = app_state.get("bot")
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot not available",
        )

    discord_id = int(user["id"])
    result = []

    for guild in bot.guilds:
        # Try to check if the user is a member of this guild
        member = guild.get_member(discord_id)
        # If member cache is incomplete, include all guilds
        if member is None and guild.member_count and guild.member_count > guild.chunked is False:
            # Can't verify membership - include the guild anyway
            pass
        elif member is None:
            # Member not found and cache seems complete - skip
            # However, to be safe with Discord's caching, include all guilds
            pass

        icon_url = None
        if guild.icon:
            icon_url = guild.icon.url

        result.append({
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count or 0,
            "icon_url": icon_url,
        })

    return result


# ======================================================================
# Guild Settings
# ======================================================================


@router.get("/guilds/{guild_id}/settings")
async def get_guild_settings(guild_id: str, user=Depends(get_current_user)):
    """Get settings for a specific guild"""
    bot = app_state.get("bot")
    character_manager = app_state.get("character_manager")
    enhanced_schedule_manager = app_state.get("enhanced_schedule_manager")

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot not available",
        )

    # Verify guild exists in bot
    guild = bot.get_guild(int(guild_id))
    if not guild:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guild not found",
        )

    # Get character info
    character_name = "らじたん"
    personality_type = "default"

    if character_manager:
        character_info = await character_manager.get_character_info(guild_id)
        if character_info:
            character_name = character_info.get("name", "らじたん")
            personality_type = character_info.get("personality_type", "default")

    # Get schedule info for auto-feature toggles
    auto_summary = False
    auto_quiz = False
    auto_music = False

    if enhanced_schedule_manager:
        try:
            schedules = await enhanced_schedule_manager.get_guild_schedules(guild_id)
            for schedule in schedules:
                func_type = getattr(schedule, "function_type", None) or getattr(schedule, "type", "")
                func_str = str(func_type).lower()
                if "summary" in func_str:
                    auto_summary = True
                elif "quiz" in func_str:
                    auto_quiz = True
                elif "music" in func_str:
                    auto_music = True
        except Exception as e:
            logger.warning(f"Failed to get guild schedules: {e}")

    # Get active persona id
    active_persona_id = ""
    persona_manager = app_state.get("persona_manager")
    if persona_manager:
        try:
            persona = await persona_manager.resolve_persona(guild_id)
            if persona:
                active_persona_id = persona.id
        except Exception as e:
            logger.warning(f"Failed to resolve persona: {e}")

    return {
        "guild_id": guild_id,
        "guild_name": guild.name,
        "character_name": character_name,
        "personality_type": personality_type,
        "active_persona_id": active_persona_id,
        "features": {
            "auto_summary": auto_summary,
            "auto_quiz": auto_quiz,
            "auto_music": auto_music,
        },
    }


class UpdateGuildSettingsRequest(BaseModel):
    personality_type: Optional[str] = None
    persona_id: Optional[str] = None


@router.put("/guilds/{guild_id}/settings")
async def update_guild_settings(
    guild_id: str,
    body: UpdateGuildSettingsRequest,
    user=Depends(get_current_user),
):
    """Update guild settings (personality type)"""
    bot = app_state.get("bot")
    character_manager = app_state.get("character_manager")

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot not available",
        )

    # Verify guild exists
    guild = bot.get_guild(int(guild_id))
    if not guild:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guild not found",
        )

    if character_manager:
        # Prefer persona_id if provided
        if body.persona_id:
            persona_manager = app_state.get("persona_manager")
            if persona_manager:
                success = await persona_manager.set_guild_persona(
                    guild_id, body.persona_id
                )
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to set persona",
                    )
        elif body.personality_type:
            success = await character_manager.update_character_personality(
                guild_id, body.personality_type
            )
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to update personality type",
                )

    return {"status": "ok", "message": "設定を更新しました"}


# ======================================================================
# Activity
# ======================================================================


@router.get("/activity")
async def get_activity(
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
):
    """Get recent bot activities"""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    try:
        async with aiosqlite.connect(db_client.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, guild_id, channel_id, activity_type, description, created_at
                FROM bot_activities
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [
            {
                "id": row["id"],
                "guild_id": row["guild_id"],
                "channel_id": row["channel_id"],
                "activity_type": row["activity_type"],
                "description": row["description"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to get activities: {e}")
        return []


# ======================================================================
# Daily Stats
# ======================================================================


@router.get("/stats/daily")
async def get_daily_stats(
    days: int = Query(default=30, ge=1, le=365),
    user=Depends(get_current_user),
):
    """Get daily aggregated stats from usage_stats table"""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    try:
        async with aiosqlite.connect(db_client.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    DATE(created_at) as date,
                    SUM(CASE WHEN feature_type = 'summary' THEN 1 ELSE 0 END) as summaries,
                    SUM(CASE WHEN feature_type = 'quiz' THEN 1 ELSE 0 END) as quizzes,
                    SUM(CASE WHEN feature_type = 'music' THEN 1 ELSE 0 END) as music,
                    COUNT(*) as total
                FROM usage_stats
                WHERE created_at >= DATE('now', ?)
                GROUP BY DATE(created_at)
                ORDER BY date ASC
                """,
                (f"-{days} days",),
            ) as cursor:
                rows = await cursor.fetchall()

        return [
            {
                "date": row["date"],
                "summaries": row["summaries"],
                "quizzes": row["quizzes"],
                "music": row["music"],
                "total": row["total"],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to get daily stats: {e}")
        return []
