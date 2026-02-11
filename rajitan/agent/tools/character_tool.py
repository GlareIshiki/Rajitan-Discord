from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.persona.identity import update_bot_identity
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

    def __init__(self, persona_manager, bot):
        self.persona_manager = persona_manager
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

        # Set via persona manager
        success = await self.persona_manager.set_guild_persona(guild_id, persona_id)
        if success:
            await self._apply_identity(guild_id)
            return ToolResult(success=True, data=f"ペルソナを「{value}」に変更したよ！")

        return ToolResult(success=False, error="ペルソナの変更に失敗した。指定した名前またはIDを確認して。")

    async def _apply_identity(self, guild_id: str) -> None:
        """Update bot nickname/avatar to match the switched persona."""
        try:
            persona = await self.persona_manager.resolve_persona(guild_id)
            if persona:
                await update_bot_identity(self.bot, guild_id, persona)
        except Exception as e:
            logger.warning(f"Identity update failed: {e}")
