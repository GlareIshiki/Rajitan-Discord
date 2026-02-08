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

PARTICIPATE_PROMPT = """あなたはDiscordボット「らじたん」（Rajitan）です。
今、ユーザーと会話中で、直近にあなたも会話に参加していました。

最近の会話:
{recent_messages}

新しいメッセージ: {new_message}

このメッセージに反応すべきですか？

- YES: あなたに話しかけている、あなたの発言への返事、会話の流れで自然に返せる
- SKIP: 明らかに他の人への発言、自分に全く関係ない話題
- LEAVE: 「もういいよ」「うるさい」等、あなたの参加を明確に拒否されている

迷ったらYESにしてください。あなたは会話の参加者なので、反応するのが自然です。

YES、SKIP、LEAVEのどれか1つだけ答えてください。"""


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

    async def should_participate(self, new_message: str, recent_messages: str) -> str:
        """会話ウィンドウ内での参加判定。"yes"/"skip"/"leave" を返す。失敗時は"skip"。"""
        try:
            return await asyncio.wait_for(
                self._judge_participation(new_message, recent_messages),
                timeout=10.0,
            )
        except Exception as e:
            logger.warning(f"Participation check failed, defaulting to skip: {e}")
            return "skip"

    async def _judge_participation(self, new_message: str, recent_messages: str) -> str:
        prompt = PARTICIPATE_PROMPT.format(
            recent_messages=recent_messages,
            new_message=new_message,
        )
        # Stage 1: Thinking mode — deep reasoning
        result = await self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0,
            thinking=True,
        )

        # If content came back directly, use it
        if result and (result.content or "").strip():
            answer = result.content.strip().upper()
            return self._parse_participation(answer, new_message)

        # Stage 2: Feed reasoning to non-thinking for clean extraction
        reasoning = (result.reasoning_content or "") if result else ""
        if not reasoning:
            logger.warning(f"Participation: no reasoning, defaulting to skip")
            return "skip"

        extract = await self.llm.chat_completion(
            messages=[{
                "role": "user",
                "content": f"以下の分析に基づいて、YES、SKIP、LEAVEのどれか1つだけ答えてください。\n\n{reasoning}",
            }],
            max_tokens=5,
            temperature=0,
            thinking=False,
        )
        if extract is None:
            return "skip"
        answer = (extract.content or "").strip().upper()
        logger.debug(f"Participation stage2 answer: '{answer}'")
        return self._parse_participation(answer, new_message)

    def _parse_participation(self, answer: str, new_message: str) -> str:
        if "LEAVE" in answer:
            logger.info(f"Participation: LEAVE — {new_message[:60]}...")
            return "leave"
        if "YES" in answer:
            logger.info(f"Participation: YES — {new_message[:60]}...")
            return "yes"
        logger.info(f"Participation: SKIP (raw='{answer[:30]}') — {new_message[:60]}...")
        return "skip"
