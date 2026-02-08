from typing import Any, Dict, List, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.schedule")


class ScheduleCreateTool(Tool):
    """スケジュール作成ツール"""

    name = "schedule_create"
    description = "定期的または一回限りのスケジュールを作成する。要約・クイズ・音楽レコメンドを指定した時間に自動実行できる。"
    parameters = {
        "type": "object",
        "properties": {
            "function_type": {
                "type": "string",
                "description": "実行する機能の種類",
                "enum": ["summary", "quiz", "music"],
            },
            "pattern_type": {
                "type": "string",
                "description": "スケジュールのパターン",
                "enum": ["hourly", "daily", "weekly", "monthly", "once"],
            },
            "hour": {
                "type": "integer",
                "description": "実行する時間（0-23）",
                "minimum": 0,
                "maximum": 23,
            },
            "minute": {
                "type": "integer",
                "description": "実行する分（0-59、デフォルト: 0）",
                "minimum": 0,
                "maximum": 59,
                "default": 0,
            },
            "day_of_week": {
                "type": "integer",
                "description": "曜日（0=月曜〜6=日曜、weeklyの場合に使用）",
                "minimum": 0,
                "maximum": 6,
            },
        },
        "required": ["function_type", "pattern_type", "hour"],
    }

    def __init__(self, schedule_manager):
        self.manager = schedule_manager

    async def execute(
        self,
        *,
        agent_context=None,
        function_type: str = "summary",
        pattern_type: str = "daily",
        hour: int = 0,
        minute: int = 0,
        day_of_week: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        from rajitan.scheduler.schedule_models import ScheduleInfo

        schedule_info = ScheduleInfo(
            channel_id=agent_context.channel_id,
            guild_id=agent_context.guild_id,
            function_type=function_type,
            pattern_type=pattern_type,
            hour=hour,
            minute=minute,
            day_of_week=day_of_week,
            created_by=agent_context.user_id,
            is_active=True,
        )

        success = await self.manager.create_schedule(schedule_info)
        if success:
            return ToolResult(success=True, data=f"スケジュールを作成したよ！{function_type}を{pattern_type}で{hour:02d}:{minute:02d}に実行するね。")
        return ToolResult(success=False, error="スケジュールの作成に失敗した。")


class ScheduleListTool(Tool):
    """スケジュール一覧ツール"""

    name = "schedule_list"
    description = "現在のチャンネルに設定されているスケジュール一覧を表示する。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, schedule_manager):
        self.manager = schedule_manager

    async def execute(self, *, agent_context=None, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        schedules = await self.manager.get_channel_schedules(agent_context.channel_id)
        if not schedules:
            return ToolResult(success=True, data="このチャンネルにはスケジュールが設定されていないよ。")

        lines = ["📅 **スケジュール一覧**"]
        for s in schedules:
            lines.append(f"- ID:{s.id} | {s.function_type} | {s.pattern_type} | {s.hour:02d}:{s.minute:02d} | {'有効' if s.is_active else '無効'}")

        return ToolResult(success=True, data="\n".join(lines))


class ScheduleDeleteTool(Tool):
    """スケジュール削除ツール"""

    name = "schedule_delete"
    description = "指定したスケジュールを削除する。schedule_listで取得したIDを使う。"
    parameters = {
        "type": "object",
        "properties": {
            "schedule_id": {
                "type": "integer",
                "description": "削除するスケジュールのID",
            },
        },
        "required": ["schedule_id"],
    }

    def __init__(self, schedule_manager):
        self.manager = schedule_manager

    async def execute(self, *, agent_context=None, schedule_id: int = 0, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        success = await self.manager.delete_schedule(schedule_id)
        if success:
            return ToolResult(success=True, data=f"スケジュール(ID:{schedule_id})を削除したよ。")
        return ToolResult(success=False, error=f"スケジュール(ID:{schedule_id})の削除に失敗した。存在しないかもしれない。")
