"""
TeammateRunner — Role-specialized agent loop with team communication.

Each teammate has a unique role, filtered tool access, and can communicate
with other teammates via team_report/team_message tools.
Self-claims next available task for its role after completing one.
"""

import json
import time
from typing import Any, Dict, List, Optional

from rajitan.agent.context_manager import ContextManager
from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.teams.mailbox import TeamMailbox
from rajitan.agent.teams.models import TeamRole, TeamTask, TeammateResult
from rajitan.agent.teams.task_graph import TaskGraph
from rajitan.agent.tools.base import ToolRegistry
from rajitan.agent.workflow.schema import AgentTeamsConfig, ContextConfig
from rajitan.utils.logger import get_logger

logger = get_logger("agent.teams.teammate")

_TEAMMATE_MAX_CALLS_PER_TOOL = 3

# Team tool definitions (injected into teammate's tool list, handled inline)
_TEAM_REPORT_DEF = {
    "type": "function",
    "function": {
        "name": "team_report",
        "description": "リーダーに報告する。重要な発見や最終結果を報告すること。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "報告内容",
                },
                "is_final": {
                    "type": "boolean",
                    "description": "最終報告ならtrue",
                },
            },
            "required": ["content"],
        },
    },
}

_TEAM_MESSAGE_DEF = {
    "type": "function",
    "function": {
        "name": "team_message",
        "description": "他のチームメイトにメッセージを送る。情報共有や質問に使う。",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "送り先のチームメイトID",
                },
                "content": {
                    "type": "string",
                    "description": "メッセージ内容",
                },
            },
            "required": ["to", "content"],
        },
    },
}

_TEAM_TOOLS = {"team_report", "team_message"}


class TeammateRunner:
    """Role-specialized agent loop with team tools and self-claiming."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentTeamsConfig,
        task_graph: TaskGraph,
        mailbox: TeamMailbox,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.cfg = config
        self.task_graph = task_graph
        self.mailbox = mailbox
        self.context_manager = ContextManager(
            context_config=ContextConfig(
                warning_threshold=30_000,
                keep_last_n_exchanges=3,
                chars_per_token=3,
                summary_keep_entries=4,
            )
        )

    async def run(
        self,
        teammate_id: str,
        role: TeamRole,
        initial_task: TeamTask,
        agent_context: Any,
        all_roles: Dict[str, TeamRole],
        exec_id: str = "",
    ) -> List[TeammateResult]:
        """Execute tasks until no more claimable tasks exist for this role.

        Self-claims additional tasks after completing each one.
        Returns list of TeammateResult (one per task completed).
        """
        results: List[TeammateResult] = []
        current_task = initial_task

        while current_task is not None:
            # Claim the task
            claimed = await self.task_graph.claim_task(current_task.task_id, teammate_id)
            if not claimed:
                logger.info(f"Teammate [{teammate_id}] could not claim {current_task.task_id}")
                break

            logger.info(
                f"Teammate [{teammate_id}] ({role.display_name}) "
                f"starting task {current_task.task_id}: {current_task.description[:50]}"
            )

            # Execute the task
            result = await self._execute_task(
                teammate_id, role, current_task, agent_context, all_roles,
            )
            results.append(result)

            # Record result in task graph
            if result.success:
                unblocked = await self.task_graph.complete_task(
                    current_task.task_id, result.data,
                )
                if unblocked:
                    logger.info(f"Teammate [{teammate_id}] unblocked: {unblocked}")
            else:
                await self.task_graph.fail_task(
                    current_task.task_id, result.error or "unknown",
                )

            # Self-claim: look for more tasks for this role
            claimable = await self.task_graph.get_claimable(role_id=role.role_id)
            current_task = claimable[0] if claimable else None

        return results

    async def _execute_task(
        self,
        teammate_id: str,
        role: TeamRole,
        task: TeamTask,
        agent_context: Any,
        all_roles: Dict[str, TeamRole],
    ) -> TeammateResult:
        """Execute a single task with an agent loop."""
        start_time = time.time()
        tools_used: List[str] = []
        total_tokens = 0
        max_steps = role.max_steps
        last_mailbox_check = start_time

        # Build filtered tool definitions
        all_tool_defs = self.tools.get_function_definitions()
        tool_defs = [
            td for td in all_tool_defs
            if td["function"]["name"] in role.allowed_tools
        ]
        # Inject team tools
        tool_defs.append(_TEAM_REPORT_DEF)
        tool_defs.append(_TEAM_MESSAGE_DEF)
        tool_defs = tool_defs or None

        # Build system prompt
        system_prompt = self._build_system_prompt(
            teammate_id, role, task, all_roles,
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.description},
        ]

        # Local call counts (isolated from shared ToolRegistry)
        call_counts: Dict[str, int] = {}

        for step in range(max_steps):
            logger.debug(f"Teammate [{teammate_id}] task {task.task_id} step {step + 1}/{max_steps}")

            # Context compaction
            if self.context_manager.should_summarize(messages):
                messages = self.context_manager.compact_context(messages)

            # Check mailbox for new messages
            new_msgs = self.mailbox.read(teammate_id, since=last_mailbox_check)
            last_mailbox_check = time.time()
            if new_msgs:
                msg_text = "\n".join(
                    f"[{m.from_id}]: {m.content}" for m in new_msgs
                )
                messages.append({
                    "role": "user",
                    "content": f"【チームメッセージ】\n{msg_text}",
                })

            # Final step: force text response
            step_tools = tool_defs
            if step == max_steps - 1:
                step_tools = None
                messages.append({
                    "role": "user",
                    "content": "【システム】最後のステップです。結果をまとめて報告してください。",
                })

            llm_response = await self.llm.chat_completion(
                messages=messages,
                tools=step_tools,
                temperature=self.cfg.teammate_temperature,
                max_tokens=self.cfg.teammate_max_tokens,
                thinking=False,
            )

            if llm_response is None:
                return TeammateResult(
                    teammate_id=teammate_id,
                    task_id=task.task_id,
                    role_id=role.role_id,
                    success=False,
                    error="LLM returned None",
                    tools_used=tools_used,
                    steps_taken=step + 1,
                    total_tokens=total_tokens,
                )

            total_tokens += llm_response.usage.get("total_tokens", 0)

            # Final text response
            if llm_response.is_final:
                elapsed = time.time() - start_time
                logger.info(
                    f"Teammate [{teammate_id}] task {task.task_id} completed "
                    f"in {step + 1} steps, {elapsed:.1f}s, tools: {tools_used}"
                )
                return TeammateResult(
                    teammate_id=teammate_id,
                    task_id=task.task_id,
                    role_id=role.role_id,
                    success=True,
                    data=llm_response.content or "",
                    tools_used=tools_used,
                    steps_taken=step + 1,
                    total_tokens=total_tokens,
                )

            # Tool calls
            if llm_response.has_tool_calls:
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": llm_response.content,
                }
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in llm_response.tool_calls
                ]
                messages.append(assistant_msg)

                for tc in llm_response.tool_calls:
                    # Handle team tools inline
                    if tc.name in _TEAM_TOOLS:
                        content = self._handle_team_tool(
                            teammate_id, tc.name, tc.arguments,
                        )
                        tools_used.append(tc.name)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": content,
                        })
                        continue

                    # Check tool is in allowed subset
                    if tc.name not in role.allowed_tools:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: {tc.name}はこのロールでは使用不可。",
                        })
                        continue

                    # Enforce local call limits
                    count = call_counts.get(tc.name, 0)
                    if count >= _TEAMMATE_MAX_CALLS_PER_TOOL:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: {tc.name}は{_TEAMMATE_MAX_CALLS_PER_TOOL}回まで。",
                        })
                        continue

                    logger.info(f"Teammate [{teammate_id}] tool: {tc.name}")
                    tools_used.append(tc.name)

                    tool_args = {**tc.arguments, "agent_context": agent_context}
                    result = await self.tools.execute(
                        tc.name, call_counts=call_counts, **tool_args,
                    )
                    call_counts[tc.name] = count + 1

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.to_content_string(),
                    })

        # Max steps exceeded
        logger.warning(f"Teammate [{teammate_id}] task {task.task_id} exceeded {max_steps} steps")
        last_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_content = msg["content"]
                break

        return TeammateResult(
            teammate_id=teammate_id,
            task_id=task.task_id,
            role_id=role.role_id,
            success=bool(tools_used),
            data=last_content or "最大ステップ超過。",
            tools_used=tools_used,
            steps_taken=max_steps,
            total_tokens=total_tokens,
            error="max_steps_exceeded" if not last_content else None,
        )

    def _build_system_prompt(
        self,
        teammate_id: str,
        role: TeamRole,
        task: TeamTask,
        all_roles: Dict[str, TeamRole],
    ) -> str:
        """Build role-specific system prompt with upstream results."""
        parts = [
            f"あなたはエージェントチームの{role.display_name}です。",
            f"\n## あなたの専門性\n{role.expertise}",
            f"\n## 現在のタスク\n{task.description}",
        ]

        # Upstream results
        upstream = self.task_graph.get_upstream_results(task.task_id)
        if upstream:
            upstream_text = "\n".join(
                f"- {tid}: {result[:500]}" for tid, result in upstream.items()
            )
            parts.append(f"\n## 前段階の結果（これらを活用してください）\n{upstream_text}")

        # Team members
        members = []
        for rid, r in all_roles.items():
            member_id = f"{rid}_1"
            if member_id == teammate_id:
                members.append(f"- {member_id}: {r.display_name}（あなた）")
            else:
                members.append(f"- {member_id}: {r.display_name}（{r.expertise}）")
        if members:
            parts.append(f"\n## チームメンバー\n" + "\n".join(members))

        parts.append(
            f"\n## コミュニケーション\n"
            f"- team_report: リーダーへの報告（重要な発見や最終結果）\n"
            f"- team_message: 他のチームメイトへの直接メッセージ\n"
            f"\n## ルール\n"
            f"- 与えられたタスクに集中する\n"
            f"- 結果はデータとして報告する（ユーザー向けの文章にしない）\n"
            f"- 最大{role.max_steps}ステップ以内で完了すること\n"
            f"- 完了したら結果をテキストでまとめること"
        )

        return "\n".join(parts)

    def _handle_team_tool(
        self, teammate_id: str, tool_name: str, args: Dict[str, Any]
    ) -> str:
        """Handle team_report and team_message tool calls inline."""
        if tool_name == "team_report":
            content = args.get("content", "")
            self.mailbox.send(teammate_id, "leader", content)
            return "報告をリーダーに送信しました。"

        if tool_name == "team_message":
            to = args.get("to", "")
            content = args.get("content", "")
            if not to or not content:
                return "Error: to と content は必須です。"
            self.mailbox.send(teammate_id, to, content)
            return f"{to}にメッセージを送信しました。"

        return f"Error: Unknown team tool: {tool_name}"
