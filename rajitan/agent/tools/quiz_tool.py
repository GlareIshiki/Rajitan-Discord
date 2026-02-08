from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.quiz")


class QuizTool(Tool):
    """クイズ生成・開始ツール"""

    name = "quiz"
    description = "最近の会話内容からクイズを生成して出題する。会話の内容を楽しくおさらいできる。"
    parameters = {
        "type": "object",
        "properties": {
            "num_questions": {
                "type": "integer",
                "description": "出題する問題数（デフォルト: 5）",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": [],
    }

    def __init__(self, quiz_generator, quiz_runner, conversation_tracker, fetch_history_fn=None):
        self.generator = quiz_generator
        self.runner = quiz_runner
        self.tracker = conversation_tracker
        self.fetch_history_fn = fetch_history_fn

    async def execute(self, *, agent_context=None, num_questions: int = 5, **kwargs) -> ToolResult:
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
            return ToolResult(success=False, error="最近の会話が見つからない。もう少し話してからクイズを頼んでね。")

        quiz = await self.generator.generate_quiz(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=messages,
            num_questions=num_questions,
        )

        if not quiz:
            return ToolResult(success=False, error="クイズの生成に失敗した。")

        started = await self.runner.start_quiz(channel_id, quiz)
        if not started:
            return ToolResult(success=False, error="クイズの開始に失敗した。")

        return ToolResult(success=True, data=f"クイズを開始したよ！{len(quiz.questions)}問出題するね！")
