"""
ResponseGate — エージェント応答の品質ゲート + 会話参加判定。

- should_send: 応答を送信すべきか（フェイルセーフ: 送信する）
- should_participate: 会話ウィンドウ内で割り込むべきか（フェイルセーフ: 割り込まない）
"""

import asyncio
from typing import TYPE_CHECKING, Optional

from rajitan.agent.workflow.schema import ResponseGateConfig
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.llm.base import LLMProvider

logger = get_logger("agent.response_gate")

# Fallback prompts used when config has empty strings
_DEFAULT_GATE_PROMPT = """あなたはDiscordボットの出力チェッカーです。
以下のボットの応答が「ユーザーに向けた回答」か「ボットの内部思考の漏れ」かを判定してください。

YES（送信する）: ユーザーに向けて書かれた回答。情報提供、案内、雑談、ツール結果の報告などすべて含む。
NO（送信しない）: ボットの内部思考が漏れている。「目的は達成できた」「最終回答をまとめよう」「次のステップとして」等の自己評価・計画。

ユーザーの発言: {user_message}

ボットの応答:
{response}

YESかNOだけ答えてください。"""

_DEFAULT_PARTICIPATE_PROMPT = """あなたはDiscordボット「らじたん」（Rajitan）です。
直前までユーザーと会話していました。会話はまだ続いています。

最近の会話:
{recent_messages}

新しいメッセージ: {new_message}

あなたはこのメッセージに返事すべきですか？

- YES: 会話が続いている。返事をする。（ほとんどの場合これ）
- SKIP: 明らかに別の人に話しかけている（名指しで他の人を呼んでいる等）
- LEAVE: 「もういいよ」「黙って」等、あなたに黙るよう求めている

会話中なので、基本はYESです。

YES、SKIP、LEAVEのどれか1つだけ答えてください。"""


class ResponseGate:
    """LLMベースの応答品質ゲート"""

    def __init__(self, llm_provider: "LLMProvider", gate_config: Optional[ResponseGateConfig] = None):
        self.llm = llm_provider
        self.cfg = gate_config or ResponseGateConfig()

    async def should_send(self, response: str, user_message: str) -> bool:
        """応答をユーザーに送信すべきか判定する。失敗時はfailsafe_send。"""
        try:
            return await asyncio.wait_for(
                self._judge(response, user_message),
                timeout=self.cfg.timeout_seconds,
            )
        except Exception as e:
            logger.warning(f"ResponseGate failed, defaulting to send={self.cfg.failsafe_send}: {e}")
            return self.cfg.failsafe_send

    async def _judge(self, response: str, user_message: str) -> bool:
        gate_prompt = self.cfg.gate_prompt or _DEFAULT_GATE_PROMPT
        prompt = gate_prompt.format(
            user_message=user_message,
            response=response,
        )
        result = await self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            thinking=self.cfg.thinking,
        )
        if result is None:
            return self.cfg.failsafe_send
        answer = (result.content or "").strip().upper()
        logger.debug(f"ResponseGate raw answer: '{answer}' for: {response[:60]}...")
        # Exact first-word match — only block on explicit "NO"
        first_word = answer.split()[0] if answer else ""
        if first_word == "NO":
            logger.info(f"ResponseGate blocked: {response[:80]}...")
            return False
        return True

    # --- 会話参加判定 ---

    async def should_participate(self, new_message: str, recent_messages: str) -> str:
        """会話ウィンドウ内での参加判定。"yes"/"skip"/"leave" を返す。失敗時はfailsafe_participate。"""
        try:
            return await asyncio.wait_for(
                self._judge_participation(new_message, recent_messages),
                timeout=self.cfg.timeout_seconds,
            )
        except Exception as e:
            logger.warning(f"Participation check failed, defaulting to {self.cfg.failsafe_participate}: {e}")
            return self.cfg.failsafe_participate

    async def _judge_participation(self, new_message: str, recent_messages: str) -> str:
        participate_prompt = self.cfg.participate_prompt or _DEFAULT_PARTICIPATE_PROMPT
        prompt = participate_prompt.format(
            recent_messages=recent_messages,
            new_message=new_message,
        )
        result = await self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            thinking=self.cfg.thinking,
        )
        if result is None:
            return self.cfg.failsafe_participate
        answer = (result.content or "").strip().upper()
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
