"""Bot Discord identity management (nickname + avatar) tied to persona."""

import discord
import httpx

from rajitan.utils.logger import get_logger

logger = get_logger("persona.identity")


async def update_bot_identity(bot, guild_id: str, persona) -> dict:
    """Update bot guild nickname and global avatar to match a persona.

    Args:
        bot: RajitanBot instance
        guild_id: Target guild ID
        persona: Persona object with display_name and avatar_url

    Returns:
        dict with results: {"nickname": ..., "avatar": ...}
    """
    result = {"nickname": "skipped", "avatar": "skipped"}

    # --- Guild nickname ---
    guild = bot.get_guild(int(guild_id))
    if guild:
        new_nick = persona.display_name if persona.display_name else None
        try:
            await guild.me.edit(nick=new_nick)
            result["nickname"] = "ok"
            logger.info(
                f"Nickname -> '{new_nick or '(reset)'}' in guild {guild_id}"
            )
        except discord.Forbidden:
            result["nickname"] = "no_permission"
            logger.warning(f"No permission to change nickname in guild {guild_id}")
        except discord.HTTPException as e:
            result["nickname"] = f"error: {e}"
            logger.warning(f"Nickname update failed in guild {guild_id}: {e}")
    else:
        result["nickname"] = "guild_not_found"

    # --- Global avatar ---
    if persona.avatar_url:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(persona.avatar_url)
                resp.raise_for_status()
                avatar_bytes = resp.content
            await bot.user.edit(avatar=avatar_bytes)
            result["avatar"] = "ok"
            logger.info(f"Avatar updated from persona '{persona.name}'")
        except discord.HTTPException as e:
            result["avatar"] = f"discord_error: {e}"
            logger.warning(f"Avatar update failed (rate limit?): {e}")
        except httpx.HTTPError as e:
            result["avatar"] = f"fetch_error: {e}"
            logger.warning(f"Failed to fetch avatar image: {e}")
        except Exception as e:
            result["avatar"] = f"error: {e}"
            logger.warning(f"Avatar update error: {e}")

    return result
