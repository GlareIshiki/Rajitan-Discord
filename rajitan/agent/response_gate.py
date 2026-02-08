"""
ResponseGate — エージェント応答の品質ゲート + 会話参加判定。

- should_send: 応答を送信すべきか（フェイルセーフ: 送信する）
- should_participate: 会話ウィンドウ内で割り込むべきか（フェイルセーフ: 割り込まない）
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

PARTICIPATE_PROMPT = """あなたはDiscordボット「らじたん」です。
今、ユーザーと会話中で、直近にあなたも会話に参加していました。

最近の会話:
{recent_messages}

新しいメッセージ: {new_message}

あなたはこのメッセージに反応すべきですか？
あなたは会話の参加者なので、基本的にはYESです。
NOにするのは: 明らかに自分に関係ない話、ユーザー同士の会話、「もういいよ」等で煙たがられている場合のみ。

YESかNOだけ答えてください。"""


class ResponseGate:
    """LLMベースの応答品質ゲート"""

    def __init__(self, llm_provider: "LLMProvider"):
        self.llm = llm_provider

    async def should_send(self, response: str, user_message: str) -> bool:
        """応答をユーザーに送信すべきか判定する。失敗時はTrue（送信）。"""
        try:
            return await asyncio.wait_for(
                self._judge(response, user_message),
                timeout=10.0,
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
            thinking=False,
        )
        if result is None:
            return True
        answer = (result.content or "").strip().upper()
        if "NO" in answer:
            logger.info(f"ResponseGate blocked: {response[:80]}...")
            return False
        return True

    # --- 会話参加判定 ---

    async def should_participate(self, new_message: str, recent_messages: str) -> bool:
        """会話ウィンドウ内で、この発言に割り込むべきか判定。失敗時はFalse（割り込まない）。"""
        try:
            return await asyncio.wait_for(
                self._judge_participation(new_message, recent_messages),
                timeout=10.0,
            )
        except Exception as e:
            logger.warning(f"Participation check failed, defaulting to no: {e}")
            return False

    async def _judge_participation(self, new_message: str, recent_messages: str) -> bool:
        prompt = PARTICIPATE_PROMPT.format(
            recent_messages=recent_messages,
            new_message=new_message,
        )
        result = await self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
            thinking=False,
        )
        if result is None:
            return False
        answer = (result.content or "").strip().upper()
        if "YES" in answer:
            logger.info(f"Participation approved: {new_message[:60]}...")
            return True
        logger.info(f"Participation declined: {new_message[:60]}...")
        return False
