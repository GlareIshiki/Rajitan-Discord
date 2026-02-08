"""
Agent system prompt builder with structured thinking protocol.

Builds the system prompt that teaches the LLM how to think before acting,
verify results, recover from errors, and respond naturally in character.
"""

from typing import TYPE_CHECKING

from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.orchestrator import AgentContext

logger = get_logger("agent.prompts")


class AgentPromptBuilder:
    """Builds structured system prompts for the thinking agent"""

    def __init__(self, character_manager, conversation_tracker):
        self.character_manager = character_manager
        self.conversation_tracker = conversation_tracker

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

        # Section 7: Recent conversation context
        conversation_section = await self._build_conversation_context(
            context.channel_id
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

1. 【理解】ユーザーが何を求めているか把握する。一文で要約できるか確認する
2. 【判断】ツールが必要か判断する。雑談や質問ならツールを使わず直接回答する
3. 【計画】複数のステップが必要なら、実行順序を決める
4. 【実行】必要なツールを適切な引数で呼び出す。一度に1つのアクションに集中する
5. 【確認】結果を確認する。ユーザーの元の目的を達成できたか判断する
6. 【応答】結果を自然な言葉でユーザーに伝える"""

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

- 4行以内で簡潔に応答する
- キャラクターの口調を維持する
- ツールの生データや内部情報をそのまま送らない。結果を自然な言葉でまとめる
- 「〜を実行しました」「〜ツールを使用しました」のような機械的な報告はしない
- ユーザーの言葉に自然に応答する形で結果を伝える"""

    async def _build_conversation_context(self, channel_id: str) -> str:
        """Fetch recent conversation for context"""
        try:
            recent_msgs = await self.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=30
            )
            if recent_msgs:
                convo_lines = []
                for m in recent_msgs[-10:]:
                    convo_lines.append(f"{m.username}: {m.content[:200]}")
                return "## 最近の会話\n" + "\n".join(convo_lines)
        except Exception as e:
            logger.warning(f"Failed to get recent conversation: {e}")
        return ""
