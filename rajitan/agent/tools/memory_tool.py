"""
RememberTool / RecallTool — エージェントが明示的に長期記憶を読み書きするツール。

エージェントが「覚えておくべき」と判断した情報をSQLiteに永続化し、
後で思い出すことができる。
"""

from rajitan.agent.memory.models import LongTermMemory
from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.memory")


class RememberTool(Tool):
    """重要な情報を長期記憶に保存する"""

    name = "remember"
    description = (
        "重要な情報を長期記憶に保存する。ユーザーの好みや特徴など、"
        "後で役立つ情報を覚えておく。同じキーで再度呼ぶと上書きされる。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["user_preference", "channel_trait", "learned_fact"],
                "description": "記憶のカテゴリ（user_preference: ユーザーの好み, channel_trait: チャンネルの特徴, learned_fact: 学んだ事実）",
            },
            "key": {
                "type": "string",
                "description": "記憶のキー（例: 'favorite_game', 'active_hours'）",
            },
            "value": {
                "type": "string",
                "description": "覚えておく内容（自然言語）",
            },
        },
        "required": ["category", "key", "value"],
    }

    def __init__(self, memory_manager):
        self.memory = memory_manager

    async def execute(
        self,
        *,
        agent_context=None,
        category: str = "",
        key: str = "",
        value: str = "",
        **kwargs,
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not category or not key or not value:
            return ToolResult(
                success=False, error="category, key, value すべて必要です"
            )

        memory = LongTermMemory(
            guild_id=agent_context.guild_id,
            category=category,
            key=key,
            value=value,
            channel_id=agent_context.channel_id,
            user_id=agent_context.user_id,
        )
        await self.memory.remember(memory)

        return ToolResult(success=True, data=f"覚えた: [{category}] {key} = {value}")


class RecallTool(Tool):
    """長期記憶から情報を思い出す"""

    name = "recall"
    description = (
        "長期記憶から情報を思い出す。ユーザーやチャンネルについて"
        "覚えていることを検索する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["user_preference", "channel_trait", "learned_fact"],
                "description": "検索するカテゴリ（省略可）",
            },
        },
        "required": [],
    }

    def __init__(self, memory_manager):
        self.memory = memory_manager

    async def execute(
        self, *, agent_context=None, category: str = None, **kwargs
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        memories = await self.memory.recall(
            guild_id=agent_context.guild_id,
            user_id=agent_context.user_id,
            category=category,
            limit=10,
        )

        if not memories:
            return ToolResult(success=True, data="長期記憶に該当する情報はない")

        lines = []
        for m in memories:
            lines.append(f"[{m.category}] {m.key}: {m.value}")

        return ToolResult(success=True, data="\n".join(lines))
