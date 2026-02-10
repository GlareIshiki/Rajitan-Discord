"""
TeamLeader — LLM-based planning (role/task graph generation) and result synthesis.
"""

import json
import re
from typing import Any, Dict, List, Optional

from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.teams.models import (
    AgentTeamsResult,
    TeamMessage,
    TeamPlan,
    TeamRole,
    TeamTask,
    TeammateResult,
)
from rajitan.agent.workflow.schema import AgentTeamsConfig
from rajitan.utils.logger import get_logger

logger = get_logger("agent.teams.leader")

# Tools that teammates must never use
_BLOCKED_TOOLS = {"send_message", "add_reaction"}

_PLAN_PROMPT = """あなたはエージェントチームのリーダーです。
ユーザーのリクエストを分析し、専門チームでの実行計画を立ててください。

## 利用可能なツール
{tool_list}

## 計画ルール
- 各ロールに異なる専門性とツールセットを割り当てる
- タスク間の依存関係を明確にする（前のタスクの結果が必要な場合はblocked_by指定）
- 独立したタスクは同じwaveで並列実行される
- 最大{max_teammates}チームメイト、最大{max_tasks}タスク
- send_message、add_reactionはツールに含めない
- ロール数は2〜{max_teammates}

## チームが必要なケース（should_use_teams: true）
- 異なる専門性が必要（調査→分析→レポート等）
- 順序依存のある複数ステップ（前の結果が次に必要）
- 大量の情報を分業で効率的に処理

## チームが不要なケース（should_use_teams: false）
- 単純な質問・雑談・挨拶
- 1つのツールで済む作業
- 全てが独立した並列タスク（サブエージェントで十分）
- タスクが1個しかない

## ユーザーのリクエスト
{user_message}

## 出力フォーマット (JSON)
```json
{{
  "should_use_teams": true,
  "reasoning": "判断理由",
  "roles": [
    {{
      "role_id": "英語の識別子",
      "display_name": "表示名",
      "expertise": "専門性の説明",
      "tools": ["使用するツール名"],
      "max_steps": 6
    }}
  ],
  "tasks": [
    {{
      "task_id": "task_1",
      "description": "タスクの説明",
      "role": "担当ロールのrole_id",
      "blocked_by": []
    }}
  ]
}}
```
JSONのみ出力してください。"""

_SYNTHESIZE_PROMPT = """あなたはエージェントチームのリーダーです。
チームメイトたちの作業結果を、ユーザーへの最終応答にまとめてください。

## キャラクター設定
{character_prompt}

## ユーザーのリクエスト
{user_message}

## チームメイトの作業結果
{results_text}

## チーム内のメッセージ（参考情報）
{messages_text}

## ルール
- キャラクター設定に従った口調で回答する
- 「チーム」「サブエージェント」「リーダー」等の内部用語は使わない
- あたかも自分一人で対応したかのように自然に回答する
- 結果をそのまま列挙せず、自然な文章にまとめる
- 失敗したタスクがあれば、わかる範囲で対応する"""


class TeamLeader:
    """LLM-based planning and synthesis for Agent Teams."""

    def __init__(self, llm_provider: LLMProvider, config: AgentTeamsConfig):
        self.llm = llm_provider
        self.cfg = config

    async def plan(
        self,
        user_message: str,
        available_tools: List[str],
        tool_descriptions: Dict[str, str],
        llm_override: LLMProvider = None,
    ) -> TeamPlan:
        """Create a team plan with roles, tasks, and dependencies.

        Returns TeamPlan with should_use_teams=False if not suitable.
        """
        # Short messages skip teams
        if len(user_message) < self.cfg.min_message_length:
            return TeamPlan(
                should_use_teams=False,
                reasoning=f"メッセージが短い（{len(user_message)}文字 < {self.cfg.min_message_length}）",
            )

        # Build tool list for prompt
        filtered_tools = [t for t in available_tools if t not in _BLOCKED_TOOLS]
        tool_list = "\n".join(
            f"- {name}: {tool_descriptions.get(name, '(説明なし)')}"
            for name in filtered_tools
        )

        prompt = _PLAN_PROMPT.format(
            tool_list=tool_list,
            max_teammates=self.cfg.max_teammates,
            max_tasks=self.cfg.max_tasks,
            user_message=user_message,
        )

        llm = llm_override or self.llm
        result = await llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.cfg.plan_max_tokens,
            temperature=self.cfg.plan_temperature,
            thinking=False,
        )

        if result is None or not result.content:
            logger.warning("Leader plan: LLM returned empty")
            return TeamPlan(should_use_teams=False, reasoning="LLM empty response")

        return self._parse_plan(result.content, set(filtered_tools))

    def _parse_plan(self, raw_content: str, available_tools: set) -> TeamPlan:
        """Parse LLM JSON output into TeamPlan with validation."""
        # Strip code fences
        text = raw_content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Leader plan: JSON parse failed: {e}")
            return TeamPlan(should_use_teams=False, reasoning="JSON parse error")

        if not isinstance(data, dict):
            return TeamPlan(should_use_teams=False, reasoning="Invalid JSON structure")

        if not data.get("should_use_teams", False):
            return TeamPlan(
                should_use_teams=False,
                reasoning=data.get("reasoning", "LLM decided teams not needed"),
            )

        # Parse roles
        roles: List[TeamRole] = []
        role_ids = set()
        for r in data.get("roles", []):
            rid = r.get("role_id", "")
            if not rid or rid in role_ids:
                continue
            role_ids.add(rid)
            # Filter to valid tools only
            tools = [t for t in r.get("tools", []) if t in available_tools]
            roles.append(TeamRole(
                role_id=rid,
                display_name=r.get("display_name", rid),
                expertise=r.get("expertise", ""),
                allowed_tools=tools,
                max_steps=min(r.get("max_steps", 8), self.cfg.teammate_max_steps),
            ))

        if len(roles) < 1:
            return TeamPlan(should_use_teams=False, reasoning="No valid roles")

        # Parse tasks
        tasks: List[TeamTask] = []
        task_ids = set()
        for t in data.get("tasks", []):
            tid = t.get("task_id", "")
            if not tid or tid in task_ids:
                continue
            role = t.get("role", "")
            if role not in role_ids:
                continue
            task_ids.add(tid)
            # Filter blocked_by to existing task_ids only
            blocked_by = [b for b in t.get("blocked_by", []) if b in task_ids or b in {
                tt.get("task_id") for tt in data.get("tasks", [])
            }]
            tasks.append(TeamTask(
                task_id=tid,
                description=t.get("description", ""),
                assigned_role=role,
                blocked_by=blocked_by,
            ))

        # Enforce limits
        tasks = tasks[:self.cfg.max_tasks]

        # Need at least 2 tasks for teams to make sense
        if len(tasks) < 2:
            return TeamPlan(
                should_use_teams=False,
                reasoning=f"タスク数不足（{len(tasks)}個）",
            )

        # Build blocks (reverse of blocked_by)
        for task in tasks:
            for other in tasks:
                if task.task_id in other.blocked_by:
                    task.blocks.append(other.task_id)

        # Cycle detection happens in TaskGraph._compute_waves()
        # We'll let it raise CyclicDependencyError if needed

        logger.info(
            f"Leader plan: {len(roles)} roles, {len(tasks)} tasks — "
            f"{data.get('reasoning', '')[:60]}"
        )

        return TeamPlan(
            should_use_teams=True,
            reasoning=data.get("reasoning", ""),
            roles=roles,
            tasks=tasks,
        )

    async def synthesize(
        self,
        user_message: str,
        teammate_results: List[TeammateResult],
        messages: List[TeamMessage],
        character_prompt: str,
        llm_override: LLMProvider = None,
    ) -> Optional[str]:
        """Synthesize all results into a final user-facing response."""
        # Build results text
        results_parts = []
        for tr in teammate_results:
            status = "成功" if tr.success else "失敗"
            results_parts.append(
                f"[{tr.role_id}/{tr.task_id}] ({status})\n"
                f"  内容: {tr.data or tr.error or '(なし)'}\n"
                f"  使用ツール: {', '.join(tr.tools_used) or 'なし'}"
            )
        results_text = "\n\n".join(results_parts) or "(結果なし)"

        # Build messages text
        if messages:
            msg_parts = [
                f"{m.from_id} → {m.to_id}: {m.content}"
                for m in messages[:20]  # Limit to avoid token overflow
            ]
            messages_text = "\n".join(msg_parts)
        else:
            messages_text = "(メッセージなし)"

        prompt = _SYNTHESIZE_PROMPT.format(
            character_prompt=character_prompt or "フレンドリーなAIアシスタント",
            user_message=user_message,
            results_text=results_text,
            messages_text=messages_text,
        )

        llm = llm_override or self.llm
        result = await llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.cfg.synthesize_max_tokens,
            temperature=self.cfg.synthesize_temperature,
            thinking=False,
        )

        if result is None or not result.content:
            logger.warning("Leader synthesize: LLM returned empty")
            return None

        return result.content
