from typing import Any, Dict, List, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.storage.levemagi_models import LMLeafCreate
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.task")


class TaskAddTool(Tool):
    """タスク追加ツール"""

    name = "task_add"
    description = "LeveMagiにタスク（Leaf）を追加する。タスクのタイトルと優先度を指定できる。"
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "タスクのタイトル",
            },
            "priority": {
                "type": "string",
                "description": "優先度",
                "enum": ["high", "medium", "low"],
                "default": "medium",
            },
            "nuts_id": {
                "type": "string",
                "description": "紐付けるプロジェクト（Nuts）のID（任意）",
            },
        },
        "required": ["title"],
    }

    def __init__(self, levemagi_client):
        self.client = levemagi_client

    async def execute(
        self,
        *,
        agent_context=None,
        title: str = "",
        priority: str = "medium",
        nuts_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not title:
            return ToolResult(success=False, error="タスクのタイトルが必要。")

        data = LMLeafCreate(title=title, priority=priority, nuts_id=nuts_id)
        leaf = await self.client.create_leaf(agent_context.user_id, data)

        if leaf:
            return ToolResult(success=True, data=f"タスク「{title}」を追加したよ！（ID: {leaf.id}）")
        return ToolResult(success=False, error="タスクの追加に失敗した。")


class TaskCompleteTool(Tool):
    """タスク完了ツール"""

    name = "task_complete"
    description = "LeveMagiのタスク（Leaf）を完了にする。経験値が獲得できる。"
    parameters = {
        "type": "object",
        "properties": {
            "leaf_id": {
                "type": "string",
                "description": "完了するタスクのID",
            },
            "actual_hours": {
                "type": "number",
                "description": "実際にかかった時間（時間単位）",
                "default": 1.0,
            },
        },
        "required": ["leaf_id"],
    }

    def __init__(self, levemagi_client):
        self.client = levemagi_client

    async def execute(
        self,
        *,
        agent_context=None,
        leaf_id: str = "",
        actual_hours: float = 1.0,
        **kwargs,
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        leaf = await self.client.complete_leaf(agent_context.user_id, leaf_id, actual_hours)
        if leaf:
            return ToolResult(
                success=True,
                data=f"タスク「{leaf.title}」を完了したよ！🎉 XP: +{leaf.xp_subtotal}",
            )
        return ToolResult(success=False, error=f"タスク(ID:{leaf_id})の完了に失敗した。")


class TaskListTool(Tool):
    """タスク一覧ツール"""

    name = "task_list"
    description = "ユーザーのタスク（Leaf）一覧を表示する。未完了タスクのリストが見られる。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, levemagi_client):
        self.client = levemagi_client

    async def execute(self, *, agent_context=None, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        leaves = await self.client.get_all_leaves(agent_context.user_id)
        if not leaves:
            return ToolResult(success=True, data="タスクはまだないよ。")

        active = [l for l in leaves if not l.completed_at]
        if not active:
            return ToolResult(success=True, data="未完了のタスクはないよ！全部完了してるね🎉")

        lines = [f"📋 **タスク一覧** ({len(active)}件)"]
        for l in active:
            lines.append(f"- [{l.priority}] {l.title} (ID: {l.id})")

        return ToolResult(success=True, data="\n".join(lines))


class ProjectListTool(Tool):
    """プロジェクト一覧ツール"""

    name = "project_list"
    description = "ユーザーのプロジェクト（Nuts）一覧を表示する。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, levemagi_client):
        self.client = levemagi_client

    async def execute(self, *, agent_context=None, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        nuts = await self.client.get_all_nuts(agent_context.user_id)
        if not nuts:
            return ToolResult(success=True, data="プロジェクトはまだないよ。")

        lines = [f"🥜 **プロジェクト一覧** ({len(nuts)}件)"]
        for n in nuts:
            lines.append(f"- {n.title} (ID: {n.id})")

        return ToolResult(success=True, data="\n".join(lines))
