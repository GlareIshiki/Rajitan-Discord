from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.summary")


class SummaryTool(Tool):
    """会話要約ツール"""

    name = "summary"
    description = "現在のチャンネルの会話を要約する。最近の会話内容をまとめて、重要なポイントを抽出する。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, conversation_summarizer, conversation_tracker, fetch_history_fn=None):
        self.summarizer = conversation_summarizer
        self.tracker = conversation_tracker
        self.fetch_history_fn = fetch_history_fn

    async def execute(self, *, agent_context=None, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        channel_id = agent_context.channel_id
        guild_id = agent_context.guild_id

        # Get conversation data
        summary_data = await self.tracker.get_conversation_summary_data(channel_id)
        messages = summary_data["messages"] if summary_data and summary_data.get("messages") else None

        # Fallback to Discord history
        if not messages and self.fetch_history_fn:
            messages = await self.fetch_history_fn(agent_context.channel, limit=50)

        if not messages:
            return ToolResult(success=False, error="最近の会話が見つからない。もう少し話してから要約を頼んでね。")

        summary = await self.summarizer.generate_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=messages,
        )

        if not summary:
            return ToolResult(success=False, error="要約の生成に失敗した。")

        formatted = await self.summarizer.format_summary_for_discord(summary)
        return ToolResult(success=True, data=formatted)
