from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.character")


class CharacterTool(Tool):
    """キャラクター設定変更ツール"""

    name = "change_personality"
    description = "Botのパーソナリティ（性格）を変更する。cheerful, calm, witty, professional, friendly, sarcastic, default から選べる。"
    parameters = {
        "type": "object",
        "properties": {
            "personality_type": {
                "type": "string",
                "description": "設定するパーソナリティの種類",
                "enum": ["default", "cheerful", "calm", "witty", "professional", "friendly", "sarcastic"],
            },
        },
        "required": ["personality_type"],
    }

    def __init__(self, character_manager):
        self.manager = character_manager

    async def execute(self, *, agent_context=None, personality_type: str = "default", **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        success = await self.manager.update_personality(
            guild_id=agent_context.guild_id,
            personality_type=personality_type,
        )

        if success:
            return ToolResult(success=True, data=f"パーソナリティを「{personality_type}」に変更したよ！")
        return ToolResult(success=False, error="パーソナリティの変更に失敗した。")
