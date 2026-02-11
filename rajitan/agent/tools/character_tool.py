from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.character.identity import update_bot_identity
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.character")


class CharacterTool(Tool):
    """キャラクター設定変更ツール"""

    name = "change_personality"
    description = (
        "Botのパーソナリティ（性格）を変更する。"
        "プリセット名（default, rajitan, cheerful, calm, witty, professional, friendly, sarcastic）"
        "またはカスタムペルソナのIDを指定できる。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "persona_name_or_id": {
                "type": "string",
                "description": "プリセット名（default, cheerful等）またはカスタムペルソナID",
            },
        },
        "required": ["persona_name_or_id"],
    }

    def __init__(self, character_manager, bot):
        self.manager = character_manager
        self.bot = bot

    async def execute(self, *, agent_context=None, persona_name_or_id: str = "default", **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        guild_id = agent_context.guild_id
        value = persona_name_or_id.strip()

        # Try as preset name first (e.g. "cheerful" → "preset_cheerful")
        preset_names = [
            "default", "rajitan", "cheerful", "calm",
            "witty", "professional", "friendly", "sarcastic",
        ]
        if value in preset_names:
            persona_id = f"preset_{value}"
        else:
            persona_id = value

        # Try setting via persona system
        if hasattr(self.manager, "set_guild_persona"):
            success = await self.manager.set_guild_persona(guild_id, persona_id)
            if success:
                await self._apply_identity(guild_id, persona_id)
                return ToolResult(success=True, data=f"ペルソナを「{value}」に変更したよ！")

        # Fallback to legacy update
        if value in preset_names:
            success = await self.manager.update_character_personality(
                guild_id=guild_id,
                personality_type=value,
            )
            if success:
                return ToolResult(success=True, data=f"パーソナリティを「{value}」に変更したよ！")

        return ToolResult(success=False, error="ペルソナの変更に失敗した。指定した名前またはIDを確認して。")

    async def _apply_identity(self, guild_id: str, persona_id: str) -> None:
        """Update bot nickname/avatar to match the switched persona."""
        try:
            persona = await self.manager.resolve_persona(guild_id)
            if not persona:
                persona = await self.manager.db_client.persona.get_persona(persona_id)
            if persona:
                await update_bot_identity(self.bot, guild_id, persona)
        except Exception as e:
            logger.warning(f"Identity update failed: {e}")
