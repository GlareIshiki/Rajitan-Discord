from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import discord

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.conversation")


async def _fetch_discord_history(
    channel: discord.TextChannel, limit: int = 15, **kwargs
) -> List[discord.Message]:
    """Fetch messages from Discord API directly."""
    try:
        messages = []
        async for msg in channel.history(limit=limit, **kwargs):
            messages.append(msg)
        messages.reverse()  # oldest first
        return messages
    except Exception as e:
        logger.warning(f"Failed to fetch Discord history: {e}")
        return []


def _format_discord_message(msg: discord.Message, max_content: int = 200) -> str:
    """Format a Discord message for display."""
    timestamp = msg.created_at.strftime("%H:%M")
    content = msg.content[:max_content] if msg.content else "(添付/embed)"
    return f"[{timestamp}] {msg.author.display_name}: {content}"


class GetConversationTool(Tool):
    """会話履歴取得ツール — Discord APIから直接取得"""

    name = "get_conversation"
    description = (
        "現在のチャンネルの会話履歴を取得する。"
        "デフォルトで直近50件。最大1000件まで指定可能。"
        "多くの会話を確認したい時に使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "取得するメッセージ件数（デフォルト: 50、最大: 1000）",
                "default": 50,
                "minimum": 1,
                "maximum": 1000,
            },
        },
        "required": [],
    }

    def __init__(self, conversation_tracker):
        self.tracker = conversation_tracker

    async def execute(self, *, agent_context=None, limit: int = 50, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        limit = min(max(limit, 1), 1000)
        messages = await _fetch_discord_history(agent_context.channel, limit=limit)

        if not messages:
            return ToolResult(success=True, data="会話履歴が見つからなかった。")

        lines = [f"直近{len(messages)}件の会話:"]
        for msg in messages:
            if not msg.author.bot:
                lines.append(_format_discord_message(msg))

        return ToolResult(success=True, data="\n".join(lines))


class SearchConversationTool(Tool):
    """会話検索ツール — キーワードで過去の会話を検索"""

    name = "search_conversation"
    description = (
        "キーワードでチャンネルの過去の会話を検索する。"
        "特定の話題や単語が出てきた会話を探したい時に使う。"
        "直近1000件の中から検索する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "検索キーワード",
            },
            "limit": {
                "type": "integer",
                "description": "検索対象のメッセージ件数（デフォルト: 200、最大: 1000）",
                "default": 200,
                "minimum": 10,
                "maximum": 1000,
            },
        },
        "required": ["keyword"],
    }

    async def execute(self, *, agent_context=None, keyword: str = "", limit: int = 200, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not keyword:
            return ToolResult(success=False, error="検索キーワードが必要です")

        limit = min(max(limit, 10), 1000)
        messages = await _fetch_discord_history(agent_context.channel, limit=limit)

        keyword_lower = keyword.lower()
        matches = [
            msg for msg in messages
            if msg.content and keyword_lower in msg.content.lower()
        ]

        if not matches:
            return ToolResult(
                success=True,
                data=f"「{keyword}」を含むメッセージは直近{limit}件の中に見つからなかった。",
            )

        lines = [f"「{keyword}」の検索結果: {len(matches)}件（直近{limit}件中）"]
        for msg in matches[-30:]:  # Show last 30 matches max
            lines.append(_format_discord_message(msg))

        return ToolResult(success=True, data="\n".join(lines))


class GetUserMessagesTool(Tool):
    """ユーザー別メッセージ取得ツール"""

    name = "get_user_messages"
    description = (
        "特定のユーザーのメッセージだけを取得する。"
        "誰が何を言っていたか確認したい時に使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "取得したいユーザーの表示名（部分一致）",
            },
            "limit": {
                "type": "integer",
                "description": "検索対象のメッセージ件数（デフォルト: 200、最大: 1000）",
                "default": 200,
                "minimum": 10,
                "maximum": 1000,
            },
        },
        "required": ["username"],
    }

    async def execute(self, *, agent_context=None, username: str = "", limit: int = 200, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not username:
            return ToolResult(success=False, error="ユーザー名が必要です")

        limit = min(max(limit, 10), 1000)
        messages = await _fetch_discord_history(agent_context.channel, limit=limit)

        username_lower = username.lower()
        matches = [
            msg for msg in messages
            if username_lower in msg.author.display_name.lower()
        ]

        if not matches:
            return ToolResult(
                success=True,
                data=f"「{username}」のメッセージは直近{limit}件の中に見つからなかった。",
            )

        lines = [f"「{username}」のメッセージ: {len(matches)}件（直近{limit}件中）"]
        for msg in matches[-30:]:
            lines.append(_format_discord_message(msg))

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
