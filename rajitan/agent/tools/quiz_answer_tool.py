"""
QuizAnswerTool — エージェントがクイズ回答を処理するツール。

エージェントが記憶（ワーキングメモリ）で「クイズ回答待ち」を認識し、
ユーザーのA-D回答を受け取って正解判定・採点を行う。
"""

from typing import Any, Dict, List

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.quiz_answer")


class QuizAnswerTool(Tool):
    """クイズの回答を処理する"""

    name = "quiz_answer"
    description = (
        "クイズの回答を処理する。ユーザーが送ったA〜D回答を受け取り、"
        "正解判定と採点を行う。ワーキングメモリにクイズ回答待ちがある場合に使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "items": {"type": "string", "enum": ["A", "B", "C", "D"]},
                "description": "ユーザーの回答リスト（Q1から順番に）",
            },
        },
        "required": ["answers"],
    }

    def __init__(self, quiz_runner, memory_manager):
        self.runner = quiz_runner
        self.memory = memory_manager

    async def execute(
        self, *, agent_context=None, answers: List[str] = None, **kwargs
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not answers:
            return ToolResult(success=False, error="回答が必要です")

        channel_id = str(agent_context.channel_id)
        user_id = str(agent_context.user_id)
        username = agent_context.username

        # クイズがアクティブか確認
        if not await self.runner.is_quiz_active(channel_id):
            return ToolResult(
                success=False, error="このチャンネルでアクティブなクイズがない"
            )

        results: List[Dict[str, Any]] = []
        total_correct = 0

        for answer in answers:
            answer = answer.upper().strip()
            result = await self.runner.submit_answer(
                channel_id, user_id, username, answer
            )
            if result is None:
                break
            if "error" in result:
                results.append({"error": result["error"]})
                break

            q_num = result["question_number"]
            is_correct = result["is_correct"]
            if is_correct:
                total_correct += 1

            results.append({
                "question": q_num,
                "answer": answer,
                "correct": is_correct,
                "correct_answer": result["correct_answer"],
            })

            # 次の問題へ進む
            next_result = await self.runner.next_question(channel_id)
            if next_result and next_result.get("quiz_finished"):
                break

        # 待ちアクションをクリア
        await self.memory.clear_pending_actions(channel_id)

        # 結果をまとめる
        total_questions = len(results)
        lines = []
        for r in results:
            if "error" in r:
                lines.append(r["error"])
                continue
            mark = "\u2b55" if r["correct"] else "\u274c"
            line = f"Q{r['question']}: {r['answer']} {mark}"
            if not r["correct"]:
                line += f" (正解: {r['correct_answer']})"
            lines.append(line)

        summary = "\n".join(lines)
        summary += f"\n\n結果: {total_correct}/{total_questions}問正解"

        # Save results to working memory for follow-up questions
        if self.memory:
            try:
                await self.memory.add_context_note(
                    channel_id,
                    f"クイズ結果({username}): {summary}",
                )
            except Exception as e:
                logger.warning(f"Failed to save quiz results to context: {e}")

        return ToolResult(success=True, data=summary)
