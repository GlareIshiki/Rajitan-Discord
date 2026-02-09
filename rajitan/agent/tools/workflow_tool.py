"""
WorkflowEditTool — チャット経由でユーザーのワークフローオーバーレイを編集するエージェントツール。
"""

from typing import TYPE_CHECKING

from rajitan.agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from rajitan.agent.workflow.editor import WorkflowEditor


class WorkflowEditTool(Tool):
    """自分のエージェントワークフローを自然言語で編集する"""

    name = "edit_workflow"
    description = (
        "自分のエージェントワークフローを自然言語で編集する。"
        "プロンプトの変更やツールの有効/無効設定が可能。"
        "例: 「もっとフレンドリーに話して」「web_searchを無効にして」"
    )
    max_calls_per_execution = 2
    parameters = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "ワークフローの変更指示（自然言語）",
            },
        },
        "required": ["instruction"],
    }

    def __init__(self, editor: "WorkflowEditor"):
        self.editor = editor

    async def execute(self, **kwargs) -> ToolResult:
        instruction = kwargs.get("instruction", "")
        if not instruction:
            return ToolResult(success=False, error="変更指示が必要です。")

        agent_context = kwargs.get("agent_context")
        if not agent_context:
            return ToolResult(success=False, error="コンテキストが取得できませんでした。")

        return await self.editor.apply_user_edit(
            instruction=instruction,
            guild_id=agent_context.guild_id,
            user_id=agent_context.user_id,
        )
