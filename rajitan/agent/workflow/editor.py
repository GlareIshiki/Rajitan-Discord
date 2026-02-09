"""
WorkflowEditor — ユーザーオーバーレイの自然言語編集。

LLMを使って自然言語指示をYAMLオーバーレイに変換し、SQLiteに保存する。
変更可能なフィールド: prompts, tools のみ。
"""

import asyncio
from typing import TYPE_CHECKING

import yaml

from rajitan.agent.tools.base import ToolResult
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.llm.base import LLMProvider
    from rajitan.agent.workflow.loader import WorkflowLoader

logger = get_logger("agent.workflow.editor")

# Fields users are allowed to override
_ALLOWED_SECTIONS = {"prompts", "tools"}

_EDIT_SYSTEM_PROMPT = """あなたはワークフロー設定エディタです。
ユーザーの指示に従い、YAMLオーバーレイを生成・修正してください。

## ルール
- 出力はYAMLのみ。説明文やマークダウンフェンスは不要
- 変更可能なセクション: prompts, tools のみ
- 変更したいフィールドだけを含める（変更しないフィールドは省略）
- 既存のオーバーレイがある場合、それをベースに修正する

## prompts セクションの構造
```
prompts:
  identity: "..."        # ボットの自己紹介
  thinking_protocol: |   # 思考プロセス
  tool_usage_guide: |    # ツール使用ガイド
  error_recovery_guide: | # エラー復旧ガイド
  response_format_guide: | # 応答フォーマット
  memory_usage_guide: |  # 記憶活用ガイド
  step_injection:
    first_step: "..."
    normal: "..."
    reflection: "..."
    urgency: "..."
    final_step: "..."
  messages:
    llm_failure: "..."
    max_steps_exceeded: "..."
    verification_nudge: "..."
    consecutive_tool_warning: "..."
    double_failure_warning: "..."
```

## tools セクションの構造
```
tools:
  defaults:
    max_calls_per_execution: 5
  overrides:
    tool_name:
      max_calls_per_execution: N
  disabled:
    - tool_name
```"""


class WorkflowEditor:
    """ユーザーオーバーレイの自然言語編集エンジン"""

    def __init__(self, llm_provider: "LLMProvider", workflow_loader: "WorkflowLoader"):
        self.llm = llm_provider
        self.loader = workflow_loader
        self._lock = asyncio.Lock()

    async def apply_user_edit(
        self, instruction: str, guild_id: str, user_id: str
    ) -> ToolResult:
        """ユーザーオーバーレイを自然言語で編集"""
        async with self._lock:
            try:
                # 1. Get current overlay
                current = await self.loader.get_user_overlay(guild_id, user_id)
                current_yaml = current or ""

                # 2. Generate edited YAML via LLM
                new_yaml = await self._generate_edited_yaml(current_yaml, instruction)
                if not new_yaml:
                    return ToolResult(
                        success=False,
                        error="YAMLの生成に失敗しました。",
                    )

                # 3. Validate
                try:
                    parsed = yaml.safe_load(new_yaml)
                except yaml.YAMLError as e:
                    return ToolResult(
                        success=False,
                        error=f"生成されたYAMLが不正です: {e}",
                    )

                if not isinstance(parsed, dict):
                    return ToolResult(
                        success=False,
                        error="YAMLがdict形式ではありません。",
                    )

                # 4. Strip disallowed sections
                sanitized = {k: v for k, v in parsed.items() if k in _ALLOWED_SECTIONS}
                if not sanitized:
                    return ToolResult(
                        success=False,
                        error="変更可能なフィールド（prompts, tools）が含まれていません。",
                    )

                sanitized_yaml = yaml.dump(
                    sanitized, allow_unicode=True, default_flow_style=False
                )

                # 5. Save to SQLite
                saved = await self.loader.save_user_overlay(guild_id, user_id, sanitized_yaml)
                if not saved:
                    return ToolResult(
                        success=False,
                        error="データベースに保存できませんでした。",
                    )

                # Build summary of what changed
                changed_sections = list(sanitized.keys())
                summary = f"ワークフローを更新しました（変更: {', '.join(changed_sections)}）"

                logger.info(f"User overlay updated: guild={guild_id}, user={user_id}, sections={changed_sections}")
                return ToolResult(success=True, data=summary)

            except Exception as e:
                logger.error(f"Failed to apply user edit: {e}")
                return ToolResult(success=False, error=f"編集に失敗しました: {e}")

    async def _generate_edited_yaml(self, current_yaml: str, instruction: str) -> str:
        """LLMを使って指示に基づきYAMLを生成"""
        if current_yaml:
            user_content = (
                f"現在のオーバーレイ:\n```yaml\n{current_yaml}\n```\n\n"
                f"指示: {instruction}\n\n"
                "上記の指示に従い、修正後のYAMLを出力してください。"
            )
        else:
            user_content = (
                "現在のオーバーレイはありません（デフォルト設定）。\n\n"
                f"指示: {instruction}\n\n"
                "上記の指示に従い、新しいYAMLオーバーレイを出力してください。"
            )

        result = await self.llm.chat_completion(
            messages=[
                {"role": "system", "content": _EDIT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=2000,
            temperature=0.3,
            thinking=False,
        )

        if result is None or not result.content:
            return ""

        # Strip markdown code fences if present
        content = result.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        return content.strip()
