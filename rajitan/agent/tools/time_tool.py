from datetime import datetime

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.time")

_WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


class GetTimeTool(Tool):
    name = "get_current_time"
    description = "現在の日時を取得する。今日の日付、現在時刻、曜日がわかる。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs) -> ToolResult:
        now = datetime.now()
        formatted = (
            f"{now.strftime('%Y年%m月%d日')}"
            f"（{_WEEKDAYS[now.weekday()]}曜日）"
            f"{now.strftime('%H時%M分')}"
        )
        return ToolResult(success=True, data=formatted)
