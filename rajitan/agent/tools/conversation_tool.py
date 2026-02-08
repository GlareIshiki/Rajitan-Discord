from typing import Any, Dict, List, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.conversation")


class GetConversationTool(Tool):
    """会話履歴取得ツール"""

    name = "get_conversation"
    description = "現在のチャンネルの最近の会話履歴を取得する。指定した時間内のメッセージを取得できる。"
    parameters = {
        "type": "object",
        "properties": {
            "duration_minutes": {
                "type": "integer",
                "description": "取得する時間範囲（分、デフォルト: 60）",
                "default": 60,
                "minimum": 5,
                "maximum": 1440,
            },
        },
        "required": [],
    }

    def __init__(self, conversation_tracker):
        self.tracker = conversation_tracker

    async def execute(self, *, agent_context=None, duration_minutes: int = 60, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        messages = await self.tracker.get_recent_conversation(
            agent_context.channel_id, duration_minutes=duration_minutes
        )

        if not messages:
            return ToolResult(success=True, data="最近の会話はないよ。")

        lines = [f"💬 **直近{duration_minutes}分の会話** ({len(messages)}件)"]
        for m in messages[-20:]:  # Last 20 messages max
            lines.append(f"- {m.username}: {m.content[:100]}")

        return ToolResult(success=True, data="\n".join(lines))


class AnalyzeMoodTool(Tool):
    """会話ムード分析ツール"""

    name = "analyze_mood"
    description = "現在の会話の活発さやムードを分析する。参加者数、活動レベル、メッセージ頻度などがわかる。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, conversation_tracker, conversation_analyzer):
        self.tracker = conversation_tracker
        self.analyzer = conversation_analyzer

    async def execute(self, *, agent_context=None, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        messages = await self.tracker.get_recent_conversation(
            agent_context.channel_id, duration_minutes=30
        )

        if not messages:
            return ToolResult(success=True, data="最近の会話がないため分析できない。")

        analysis = await self.analyzer.analyze_conversation_activity(messages)

        return ToolResult(
            success=True,
            data={
                "activity_level": analysis.get("activity_level", "unknown"),
                "message_count": analysis.get("message_count", 0),
                "participant_count": analysis.get("participant_count", 0),
                "is_active": analysis.get("is_active", False),
            },
        )
