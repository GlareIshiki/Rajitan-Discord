"""
TaskPlanner — LLM-based task decomposition and result synthesis.

Uses non-thinking mode for speed. Decomposes user requests into
sub-tasks and synthesizes sub-agent results into a final response.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.workflow.schema import TeamConfig
from rajitan.utils.logger import get_logger

logger = get_logger("agent.team.planner")


@dataclass
class SubTask:
    """A single sub-task produced by decomposition."""
    id: str
    description: str
    relevant_tools: List[str]
    priority: int = 0


@dataclass
class DecompositionResult:
    """Result of task decomposition."""
    should_use_team: bool
    sub_tasks: List[SubTask] = field(default_factory=list)
    reasoning: str = ""


_DECOMPOSE_PROMPT = """あなたはタスク分解の専門家です。
ユーザーのリクエストを分析し、並列実行可能なサブタスクに分解してください。

## 利用可能なツール
{tool_list}

## ルール
- サブタスクは最大{max_sub_agents}個まで
- 各サブタスクに使用するツール名を指定する（上記ツールから選ぶ）
- 単純なリクエスト（挨拶、雑談、1つのツールで済む質問）は分解不要 → should_use_team: false
- 分解が有効なケース: 複数の独立した情報収集、調査+実行、比較分析 など
- 依存関係がある（前のタスクの結果が次に必要）場合は分解しない → should_use_team: false
- send_message、add_reaction はサブタスクに含めない（メイン処理で行う）

## ユーザーのリクエスト
{user_message}

## 出力フォーマット (JSON)
{{
  "should_use_team": true/false,
  "reasoning": "分解理由の簡潔な説明",
  "sub_tasks": [
    {{
      "id": "task_1",
      "description": "サブタスクの説明",
      "relevant_tools": ["tool_name1", "tool_name2"],
      "priority": 1
    }}
  ]
}}

JSONのみ出力してください。"""


_SYNTHESIZE_PROMPT = """あなたはDiscordボット「らじたん」です。
複数の調査・作業の結果を、ユーザーへの最終回答としてまとめてください。

## キャラクター設定
{character_prompt}

## ユーザーの元のリクエスト
{user_message}

## 作業結果
{sub_agent_results}

## ルール
- キャラクターの口調を維持する
- 全ての結果を統合して自然にまとめる
- 「サブエージェント」「チーム」「タスク分解」等の内部用語は使わない
- 結果が矛盾する場合は、両方を提示して注意書きを添える
- ツール名やシステム的な表現は使わない
- 通常の会話は簡潔に（4行以内）、情報量が多い場合は必要な分だけ"""


# Tools that sub-agents must never use
_BLOCKED_TOOLS = {"send_message", "add_reaction"}


class TaskPlanner:
    """LLM-based task decomposition and result synthesis."""

    def __init__(self, llm_provider: LLMProvider, team_config: TeamConfig):
        self.llm = llm_provider
        self.cfg = team_config

    async def decompose(
        self,
        user_message: str,
        available_tools: List[str],
        llm_override: LLMProvider = None,
    ) -> DecompositionResult:
        """Decompose a user request into parallel sub-tasks."""
        if len(user_message) < self.cfg.min_message_length:
            return DecompositionResult(should_use_team=False, reasoning="short_message")

        # Filter blocked tools from the list shown to decomposer
        filtered_tools = [t for t in available_tools if t not in _BLOCKED_TOOLS]
        tool_list = "\n".join(f"- {t}" for t in filtered_tools)

        prompt = _DECOMPOSE_PROMPT.format(
            tool_list=tool_list,
            max_sub_agents=self.cfg.max_sub_agents,
            user_message=user_message,
        )

        llm = llm_override or self.llm
        try:
            response = await llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.cfg.decompose_temperature,
                max_tokens=self.cfg.decompose_max_tokens,
                thinking=False,
            )

            if response is None or not response.content:
                logger.warning("Decomposition LLM returned empty, falling back")
                return DecompositionResult(should_use_team=False, reasoning="llm_empty")

            return self._parse_decomposition(response.content)

        except Exception as e:
            logger.error(f"Decomposition failed: {e}, falling back")
            return DecompositionResult(should_use_team=False, reasoning=f"error: {e}")

    def _parse_decomposition(self, raw_content: str) -> DecompositionResult:
        """Parse LLM JSON output into DecompositionResult."""
        content = raw_content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            end_idx = len(lines)
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx]).strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse decomposition JSON: {content[:200]}")
            return DecompositionResult(should_use_team=False, reasoning="json_parse_error")

        should_use_team = data.get("should_use_team", False)
        reasoning = data.get("reasoning", "")

        if not should_use_team:
            return DecompositionResult(should_use_team=False, reasoning=reasoning)

        sub_tasks = []
        for task_data in data.get("sub_tasks", []):
            # Filter out blocked tools from each sub-task
            tools = [t for t in task_data.get("relevant_tools", []) if t not in _BLOCKED_TOOLS]
            sub_tasks.append(SubTask(
                id=task_data.get("id", f"task_{len(sub_tasks) + 1}"),
                description=task_data.get("description", ""),
                relevant_tools=tools,
                priority=task_data.get("priority", 0),
            ))

        # Not worth parallelizing with 0-1 sub-tasks
        if len(sub_tasks) <= 1:
            return DecompositionResult(
                should_use_team=False,
                reasoning="single_subtask",
            )

        # Enforce max limit
        sub_tasks = sub_tasks[:self.cfg.max_sub_agents]

        return DecompositionResult(
            should_use_team=True,
            sub_tasks=sub_tasks,
            reasoning=reasoning,
        )

    async def synthesize(
        self,
        user_message: str,
        sub_agent_results: List[Dict[str, Any]],
        character_prompt: str,
        llm_override: LLMProvider = None,
    ) -> Optional[str]:
        """Synthesize sub-agent results into a user-facing response."""
        results_text = ""
        for r in sub_agent_results:
            status = "成功" if r.get("success") else "失敗"
            results_text += f"\n### {r.get('description', '')}\n"
            results_text += f"状態: {status}\n"
            results_text += f"結果: {r.get('data', '(なし)')}\n"

        prompt = _SYNTHESIZE_PROMPT.format(
            character_prompt=character_prompt or "フレンドリーな口調で話すAIアシスタント",
            user_message=user_message,
            sub_agent_results=results_text,
        )

        llm = llm_override or self.llm
        try:
            response = await llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.cfg.synthesize_temperature,
                max_tokens=self.cfg.synthesize_max_tokens,
                thinking=False,
            )

            if response is None or not response.content:
                logger.warning("Synthesis LLM returned empty")
                return None

            return response.content

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return None
