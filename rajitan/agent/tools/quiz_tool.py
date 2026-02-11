import asyncio
from typing import Any, Dict, Optional

import discord

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.quiz")


class QuizTool(Tool):
    """クイズ生成・出題ツール — 会話内容からクイズを作って直接出題する"""

    name = "quiz"
    description = "最近の会話内容からクイズを生成して出題する。会話の内容を楽しくおさらいできる。"
    max_calls_per_execution = 1
    parameters = {
        "type": "object",
        "properties": {
            "num_questions": {
                "type": "integer",
                "description": "出題する問題数（デフォルト: 3）",
                "default": 3,
                "minimum": 1,
                "maximum": 5,
            },
        },
        "required": [],
    }

    def __init__(self, quiz_generator, quiz_runner, conversation_tracker, fetch_history_fn=None):
        self.generator = quiz_generator
        self.runner = quiz_runner
        self.tracker = conversation_tracker
        self.fetch_history_fn = fetch_history_fn

    async def execute(self, *, agent_context=None, num_questions: int = 3, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        channel = agent_context.channel
        channel_id = agent_context.channel_id
        guild_id = agent_context.guild_id

        # 1. Get conversation data — try Redis first, fallback to Discord API
        summary_data = await self.tracker.get_conversation_summary_data(channel_id)
        messages = summary_data["messages"] if summary_data and summary_data.get("messages") else None

        if not messages and channel:
            # Fallback: fetch from Discord API directly
            try:
                discord_msgs = []
                async for msg in channel.history(limit=50):
                    if not msg.author.bot and msg.content:
                        discord_msgs.append(msg)
                discord_msgs.reverse()

                if discord_msgs:
                    from rajitan.storage.models import Message
                    messages = [
                        Message(
                            user_id=str(m.author.id),
                            username=m.author.display_name,
                            content=m.content,
                            timestamp=m.created_at.replace(tzinfo=None),
                        )
                        for m in discord_msgs
                    ]
            except Exception as e:
                logger.warning(f"Failed to fetch Discord history for quiz: {e}")

        if not messages:
            return ToolResult(success=False, error="最近の会話が見つからない。もう少し話してからクイズを頼んでね。")

        # 2. Generate quiz
        quiz = await self.generator.generate_quiz(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=messages,
            num_questions=num_questions,
        )

        if not quiz or not quiz.questions:
            return ToolResult(success=False, error="クイズの生成に失敗した。")

        # 3. Store quiz for answer tracking
        await self.runner.start_quiz(channel_id, quiz)

        # 4. Return formatted quiz text for agent to present
        questions_text = []
        for i, q in enumerate(quiz.questions):
            question_text = f"**Q{i + 1}. {q['question']}**\n"
            for option in q.get("options", []):
                question_text += f"  {option}\n"
            questions_text.append(question_text)

        full_quiz = "\n".join(questions_text)
        full_quiz += "\n答えはA〜Dで送ってもらう形式。"

        return ToolResult(
            success=True,
            data=f"{len(quiz.questions)}問のクイズを生成した。以下の内容をユーザーに出題して:\n\n{full_quiz}",
        )
