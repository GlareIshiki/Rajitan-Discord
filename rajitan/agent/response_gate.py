"""
ResponseGate — エージェント応答の品質ゲート。

送信前にエージェントと同じLLMで「ユーザーに送るべきか」をYES/NO判定。
ステートレス。失敗時はフェイルセーフ（送信する）。
"""

import asyncio
from typing import TYPE_CHECKING

from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.llm.base import LLMProvider

logger = get_logger("agent.response_gate")

GATE_PROMPT = """あなたはDiscordボットの出力チェッカーです。
ユーザーの発言に対するボットの応答を見て、この応答をユーザーに送信すべきかを判断してください。

以下のような応答はNOです:
- 「目的は達成できた」「最終回答でまとめよう」等のボットの内部思考・自己評価が含まれている
- 「ツールを実行した」「処理が完了した」等のシステム報告
- 直前に別メッセージで同じ内容を既に送っている場合の重複

内部思考が自然な会話に混ざっている場合もNOです。

ユーザーの発言: {user_message}

ボットの応答:
{response}

この応答はユーザーに送るべき内容ですか？YESかNOだけ答えてください。"""


class ResponseGate:
    """LLMベースの応答品質ゲート"""

    def __init__(self, llm_provider: "LLMProvider"):
        self.llm = llm_provider

    async def should_send(self, response: str, user_message: str) -> bool:
        """応答をユーザーに送信すべきか判定する。失敗時はTrue（送信）。"""
        try:
            return await asyncio.wait_for(
                self._judge(response, user_message),
                timeout=3.0,
            )
        except Exception as e:
            logger.warning(f"ResponseGate failed, defaulting to send: {e}")
            return True

    async def _judge(self, response: str, user_message: str) -> bool:
        prompt = GATE_PROMPT.format(
            user_message=user_message,
            response=response,
        )
        result = await self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
        )
        if result is None:
            return True
        answer = (result.content or "").strip().upper()
        if "NO" in answer:
            logger.info(f"ResponseGate blocked: {response[:80]}...")
            return False
        return True
