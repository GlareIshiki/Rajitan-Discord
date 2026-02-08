from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.discord")


class SendMessageTool(Tool):
    """Discordメッセージ送信ツール"""

    name = "send_message"
    max_calls_per_execution = 3
    description = "現在のチャンネルに追加のメッセージを送信する。長い応答を分割して送りたい場合や、途中経過を報告する場合に使う。"
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "送信するメッセージの内容",
            },
        },
        "required": ["content"],
    }

    async def execute(self, *, agent_context=None, content: str = "", **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not content:
            return ToolResult(success=False, error="送信するメッセージが空。")

        try:
            await agent_context.message.channel.send(content)
            return ToolResult(success=True, data="メッセージを送信した。")
        except Exception as e:
            return ToolResult(success=False, error=f"メッセージ送信に失敗: {e}")


class AddReactionTool(Tool):
    """リアクション追加ツール"""

    name = "add_reaction"
    max_calls_per_execution = 3
    description = "ユーザーのメッセージにリアクション（絵文字）を追加する。"
    parameters = {
        "type": "object",
        "properties": {
            "emoji": {
                "type": "string",
                "description": "追加するリアクションの絵文字（例: 👍, ✅, 🎵）",
            },
        },
        "required": ["emoji"],
    }

    async def execute(self, *, agent_context=None, emoji: str = "👍", **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        try:
            await agent_context.message.add_reaction(emoji)
            return ToolResult(success=True, data=f"リアクション {emoji} を追加した。")
        except Exception as e:
            return ToolResult(success=False, error=f"リアクション追加に失敗: {e}")
