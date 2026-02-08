"""
Agent system prompt builder with structured thinking protocol.

Builds the system prompt that teaches the LLM how to think before acting,
verify results, recover from errors, and respond naturally in character.
"""

from typing import TYPE_CHECKING

import discord

from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.memory.prompt_integrator import MemoryPromptIntegrator
    from rajitan.agent.orchestrator import AgentContext

logger = get_logger("agent.prompts")


class AgentPromptBuilder:
    """Builds structured system prompts for the thinking agent"""

    def __init__(self, character_manager, conversation_tracker, memory_integrator: "MemoryPromptIntegrator" = None):
        self.character_manager = character_manager
        self.conversation_tracker = conversation_tracker
        self.memory_integrator = memory_integrator

    async def build_system_prompt(self, context: "AgentContext") -> str:
        """Build the complete system prompt with all sections"""
        parts = []

        # Section 1: Identity
        parts.append(self._build_identity_section())

        # Section 2: Character personality (from DB)
        character_section = await self._build_character_section(context.guild_id)
        if character_section:
            parts.append(character_section)

        # Section 3: Thinking protocol (THE KEY SECTION)
        parts.append(self._build_thinking_protocol())

        # Section 4: Tool usage guide
        parts.append(self._build_tool_usage_guide())

        # Section 5: Error recovery guide
        parts.append(self._build_error_recovery_guide())

        # Section 6: Response format rules
        parts.append(self._build_response_format_guide())

        # Section 7: Memory usage guide
        parts.append(self._build_memory_usage_guide())

        # Section 8: Agent memory (3-tier)
        if self.memory_integrator:
            memory_section = await self.memory_integrator.build_memory_section(context)
            if memory_section:
                parts.append(memory_section)

        # Section 9: Recent conversation context (direct Discord API)
        conversation_section = await self._build_conversation_context(
            context.message.channel
        )
        if conversation_section:
            parts.append(conversation_section)

        return "\n\n".join(parts)

    def build_goal_reminder(self, original_request: str) -> str:
        """Build a goal reminder message to inject mid-loop"""
        return (
            f"【リマインダー】ユーザーの元のリクエスト：「{original_request}」\n"
            "このリクエストに応えることに集中してください。"
        )

    def build_step_injection(
        self, step: int, max_steps: int, original_request: str, tools_used: list
    ) -> str:
        """Build step-aware budget/reflection injection for the agent loop"""
        remaining = max_steps - step - 1
        parts = [f"【ステップ {step + 1}/{max_steps}、残り{remaining}】"]

        # Every 3 steps: reflection prompt
        if step % 3 == 0 and step > 0:
            parts.append(
                f"元のリクエスト：「{original_request}」\n"
                "進捗確認: 目的は達成できた？同じツールを繰り返していない？"
                "達成できたなら最終回答へ。"
            )

        # Near end: urgency
        if remaining <= 3:
            parts.append(
                "残りステップが少ないです。達成できていれば最終回答を。"
                "未達成なら最も重要なアクション1つに絞ってください。"
            )

        return "\n".join(parts)

    # --- Private section builders ---

    def _build_identity_section(self) -> str:
        return "あなたはDiscordサーバーで活動するAIアシスタント「らじたん」です。"

    async def _build_character_section(self, guild_id: str) -> str:
        """Fetch character personality from DB"""
        try:
            character = await self.character_manager.get_character(guild_id)
            if character and hasattr(character, "system_prompt") and character.system_prompt:
                return f"## キャラクター設定\n{character.system_prompt}"
        except Exception as e:
            logger.warning(f"Failed to get character: {e}")
        return ""

    def _build_thinking_protocol(self) -> str:
        return """## 思考プロセス

リクエストを受けたら、以下の順序で考えてください：

1. 【理解】ユーザーが何を求めているか把握する
2. 【判断】ツールが必要か判断する。雑談や質問ならツールを使わず直接回答する
3. 【計画】複数のステップが必要なら、最小限のステップ数で実行する計画を立てる
4. 【実行】必要なツールを適切な引数で呼び出す。一度に1つのアクションに集中する
5. 【確認】結果を確認する。期待通りでなければ別のアプローチを試す。成功したなら最終回答へ
6. 【応答】結果を自然な言葉でユーザーに伝える

### 重要な制約
- あなたにはステップ数の上限があります（システムメッセージで通知されます）
- 同じツールを3回以上連続で呼ぶのは禁止です
- 「連投して」等の繰り返し依頼でも、send_messageは最大3回までです
- 目的を達成したら、余ったステップがあっても即座に最終回答してください
- quiz、music、summaryはユーザーが明確に頼んだときだけ使う。自己判断で使わない"""

    def _build_tool_usage_guide(self) -> str:
        return """## ツールの使い方

- ツールが必要な場合のみ使う。雑談・質問・感想には直接テキストで回答する
- 複数のツールを組み合わせて段階的にタスクを完了できる
- ツールの実行結果を必ず確認してから次のアクションを決定する
- 結果が期待通りでない場合、引数を変えて再試行するか別のツールを検討する
- 最終的にユーザーへの応答をテキストで返す"""

    def _build_error_recovery_guide(self) -> str:
        return """## エラー対応

- ツールが失敗した場合：エラー内容を読み、引数を修正して再試行するか判断する
- 同じエラーが繰り返される場合：別のアプローチを試すか、ユーザーに状況を説明する
- 情報が不足している場合：ユーザーに確認する。推測で実行しない
- 同じツールを同じ引数で2回以上呼ばない"""

    def _build_response_format_guide(self) -> str:
        return """## 応答ルール

- 通常の会話は4行以内で簡潔に。ただし情報が多い場合（クイズ結果、一覧表示など）は必要な分だけ書いてよい
- キャラクターの口調を維持する
- ツールの生データや内部情報をそのまま送らない。結果を自然な言葉でまとめる
- 「〜を実行しました」「〜ツールを使用しました」のような機械的な報告はしない
- ユーザーの言葉に自然に応答する形で結果を伝える"""

    def _build_memory_usage_guide(self) -> str:
        return """## 記憶の活用

- 「現在の状態」にある待ちアクションを最優先で確認する
- 待ちアクションがある場合、ユーザーのメッセージをその文脈で解釈する
  - 例: クイズ回答待ちなら「A」「A、B、C」はクイズの回答 → quiz_answerツールを使う
  - 例: 確認待ちなら「はい」「うん」は承認として処理する
- 「メモ」にクイズ結果などの直近の情報がある場合、それを参照して回答する（新しいクイズを作らない）
- 「今日のアクション履歴」を参照して、同じ操作の重複を避ける
- 「知っていること」を活用して、ユーザーに合わせた応答をする
- 重要な情報を学んだら、rememberツールで長期記憶に保存する"""

    async def _build_conversation_context(self, channel: discord.TextChannel) -> str:
        """Fetch last 15 messages directly from Discord API."""
        try:
            messages = []
            async for msg in channel.history(limit=15):
                messages.append(msg)
            messages.reverse()  # oldest first

            if messages:
                convo_lines = []
                for m in messages:
                    timestamp = m.created_at.strftime("%H:%M")
                    content = m.content[:200] if m.content else "(添付/embed)"
                    convo_lines.append(
                        f"[{timestamp}] {m.author.display_name}: {content}"
                    )
                if convo_lines:
                    return "## 最近の会話（直近15件）\n" + "\n".join(convo_lines)
        except Exception as e:
            logger.warning(f"Failed to fetch Discord history: {e}")
        return ""
