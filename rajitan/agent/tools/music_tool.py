from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.music")


class MusicTool(Tool):
    """音楽レコメンドツール"""

    name = "music"
    description = "会話の雰囲気に合った音楽をおすすめする。ムード分析に基づいて曲を提案し、YouTubeやSpotifyのリンクを提供する。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, music_recommender, conversation_tracker, fetch_history_fn=None):
        self.recommender = music_recommender
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

        if not messages and self.fetch_history_fn:
            messages = await self.fetch_history_fn(agent_context.message.channel, limit=50)

        if not messages:
            return ToolResult(success=False, error="最近の会話が見つからない。もう少し話してから音楽をおすすめするね。")

        recommendation = await self.recommender.generate_recommendation(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=messages,
        )

        if not recommendation:
            return ToolResult(success=False, error="音楽レコメンドの生成に失敗した。")

        # Format recommendation as string
        parts = [f"🎵 **{recommendation.title}** - {recommendation.artist}"]
        if hasattr(recommendation, "reason") and recommendation.reason:
            parts.append(f"💬 {recommendation.reason}")
        if hasattr(recommendation, "url") and recommendation.url:
            parts.append(f"🔗 {recommendation.url}")

        return ToolResult(success=True, data="\n".join(parts))
