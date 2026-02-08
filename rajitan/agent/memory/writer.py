"""
AgentMemoryWriter — エージェント実行後の自動記憶書き込み。

orchestrator.execute() の戻り値を受け取り、3層に適切に書き込む。
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional

from rajitan.agent.memory.models import (
    ActionLogEntry,
    LongTermMemory,
    PendingAction,
    PendingActionType,
)
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.memory.manager import MemoryManager
    from rajitan.agent.orchestrator import AgentContext, AgentResult

logger = get_logger("agent.memory.writer")

# ツール名 → 待ちアクションのマッピング（拡張しやすい設定）
PENDING_ACTION_TRIGGERS: Dict[str, dict] = {
    "quiz": {
        "action_type": PendingActionType.QUIZ_ANSWERS,
        "description": "クイズを出題済み。ユーザーのA〜D回答を待っている",
        "ttl_minutes": 30,
    },
}

# ツール名 → アクション要約テンプレート
ACTION_SUMMARIES: Dict[str, str] = {
    "summary": "会話を要約した",
    "quiz": "クイズを出題した",
    "quiz_answer": "クイズの回答を処理した",
    "music": "音楽をおすすめした",
    "schedule_create": "スケジュールを作成した",
    "schedule_list": "スケジュール一覧を表示した",
    "schedule_delete": "スケジュールを削除した",
    "task_add": "タスクを追加した",
    "task_complete": "タスクを完了した",
    "task_list": "タスク一覧を表示した",
    "project_list": "プロジェクト一覧を表示した",
    "get_conversation": "会話履歴を取得した",
    "search_conversation": "会話を検索した",
    "get_user_messages": "ユーザーのメッセージを取得した",
    "analyze_mood": "会話のムードを分析した",
    "character": "キャラクターを変更した",
    "send_message": "メッセージを送信した",
    "add_reaction": "リアクションを追加した",
    "remember": "情報を記憶した",
    "recall": "記憶を思い出した",
}


class AgentMemoryWriter:
    """エージェント実行結果を3層の記憶に書き込む"""

    def __init__(self, memory_manager: "MemoryManager"):
        self.memory = memory_manager

    async def process_result(
        self, result: "AgentResult", context: "AgentContext"
    ):
        """execute()完了後に呼ばれる。3層に適切に書き込む"""
        try:
            # Tier 2: アクションログ（ツールを使った場合のみ）
            seen_tools = set()
            for tool_name in result.tools_used:
                if tool_name in seen_tools:
                    continue
                seen_tools.add(tool_name)
                summary = ACTION_SUMMARIES.get(tool_name, f"{tool_name}を実行した")
                await self.memory.log_action(
                    ActionLogEntry(
                        tool_name=tool_name,
                        summary=summary,
                        channel_id=context.channel_id,
                        user_id=context.user_id,
                        success=result.success,
                    )
                )

            # Tier 1: 待ちアクション検出
            await self._detect_and_set_pending_actions(result, context)

            # Tier 3: ツール使用パターンの長期学習
            await self._update_long_term_patterns(result, context)

        except Exception as e:
            logger.error(f"Failed to process agent result for memory: {e}")

    async def _detect_and_set_pending_actions(
        self, result: "AgentResult", context: "AgentContext"
    ):
        """ツール使用結果から待ちアクションを設定"""
        # quiz_answerが使われた場合、pending_actionをクリア
        if "quiz_answer" in result.tools_used:
            await self.memory.clear_pending_actions(context.channel_id)
            return

        for tool_name in result.tools_used:
            trigger = PENDING_ACTION_TRIGGERS.get(tool_name)
            if trigger and result.success:
                ttl = trigger.get("ttl_minutes", 60)
                action = PendingAction(
                    action_type=trigger["action_type"],
                    description=trigger["description"],
                    expires_at=datetime.now() + timedelta(minutes=ttl),
                )
                await self.memory.set_pending_action(
                    context.channel_id, action
                )
                logger.info(
                    f"Set pending action: {trigger['action_type'].value} "
                    f"in channel {context.channel_id}"
                )

    async def _update_long_term_patterns(
        self, result: "AgentResult", context: "AgentContext"
    ):
        """ツール使用からユーザーの好みパターンを学習（Tier 3）"""
        if not result.tools_used or not result.success:
            return

        # ユーザーがクイズを頼んだ → 好みとして記録
        for tool_name in result.tools_used:
            if tool_name in ("quiz", "music", "summary"):
                try:
                    await self.memory.remember(
                        LongTermMemory(
                            guild_id=context.guild_id,
                            category="user_preference",
                            key=f"uses_{tool_name}",
                            value=f"この機能をよく使う（最終使用: {datetime.now().strftime('%Y-%m-%d %H:%M')}）",
                            user_id=context.user_id,
                            channel_id=context.channel_id,
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to update long-term pattern: {e}")
