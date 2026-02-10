"""
SubAgentRunner — Lightweight agent loop for focused sub-tasks.

Each sub-agent runs an independent message context with a subset of tools.
It does NOT send Discord messages and does NOT write memory.
Returns structured SubAgentResult for the coordinator to synthesize.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rajitan.agent.context_manager import ContextManager
from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.team.planner import SubTask
from rajitan.agent.tools.base import ToolRegistry
from rajitan.agent.workflow.schema import ContextConfig, TeamConfig
from rajitan.utils.logger import get_logger

logger = get_logger("agent.team.sub_agent")


@dataclass
class SubAgentResult:
    """Structured result from a sub-agent execution."""
    task_id: str
    description: str
    success: bool
    data: str = ""
    tools_used: List[str] = field(default_factory=list)
    steps_taken: int = 0
    total_tokens: int = 0
    error: Optional[str] = None


_SUB_AGENT_SYSTEM_PROMPT = """あなたは情報収集・作業実行を担当するサブエージェントです。

## あなたのタスク
{task_description}

## ルール
- 与えられたタスクだけに集中する
- 結果はデータとして返す（ユーザー向けの文章にしない）
- ツールの実行結果を正確に報告する
- 失敗した場合はエラー内容を明確に報告する
- 最大{max_steps}ステップ以内で完了すること
- 完了したら結果をテキストでまとめること（最終応答）"""

# Sub-agent tool call limit (per tool, per sub-agent)
_SUB_AGENT_MAX_CALLS_PER_TOOL = 3


class SubAgentRunner:
    """Runs a lightweight agent loop for a single sub-task."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        team_config: TeamConfig,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.cfg = team_config
        self.context_manager = ContextManager(
            context_config=ContextConfig(
                warning_threshold=30_000,
                keep_last_n_exchanges=3,
                chars_per_token=3,
                summary_keep_entries=4,
            )
        )

    async def execute(
        self,
        sub_task: SubTask,
        agent_context: Any,
        exec_id: str = "",
    ) -> SubAgentResult:
        """Execute a sub-task with a focused agent loop."""
        start_time = time.time()
        tools_used: List[str] = []
        total_tokens = 0
        max_steps = self.cfg.sub_agent_max_steps

        logger.info(
            f"SubAgent [{sub_task.id}] starting: {sub_task.description[:60]} "
            f"(tools: {sub_task.relevant_tools})"
        )

        # Build filtered tool definitions
        all_tool_defs = self.tools.get_function_definitions()
        tool_defs = [
            td for td in all_tool_defs
            if td["function"]["name"] in sub_task.relevant_tools
        ] or None

        # Build system prompt
        system_prompt = _SUB_AGENT_SYSTEM_PROMPT.format(
            task_description=sub_task.description,
            max_steps=max_steps,
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": sub_task.description},
        ]

        # Local call counts (isolated from shared ToolRegistry state)
        call_counts: Dict[str, int] = {}

        for step in range(max_steps):
            logger.debug(f"SubAgent [{sub_task.id}] step {step + 1}/{max_steps}")

            if self.context_manager.should_summarize(messages):
                messages = self.context_manager.compact_context(messages)

            # Final step: force text response
            step_tools = tool_defs
            step_max_tokens = self.cfg.sub_agent_max_tokens
            if step == max_steps - 1:
                step_tools = None
                messages.append({
                    "role": "user",
                    "content": "【システム】最後のステップです。これまでの結果をまとめて報告してください。",
                })

            llm_response = await self.llm.chat_completion(
                messages=messages,
                tools=step_tools,
                temperature=self.cfg.sub_agent_temperature,
                max_tokens=step_max_tokens,
                thinking=False,
            )

            if llm_response is None:
                return SubAgentResult(
                    task_id=sub_task.id,
                    description=sub_task.description,
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
                    f"SubAgent [{sub_task.id}] completed in {step + 1} steps, "
                    f"{elapsed:.1f}s, tools: {tools_used}"
                )
                return SubAgentResult(
                    task_id=sub_task.id,
                    description=sub_task.description,
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
                    # Check tool is in allowed subset
                    if tc.name not in sub_task.relevant_tools:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: {tc.name}はこのサブタスクでは使用不可。",
                        })
                        continue

                    # Enforce local call limits
                    count = call_counts.get(tc.name, 0)
                    if count >= _SUB_AGENT_MAX_CALLS_PER_TOOL:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: {tc.name}は{_SUB_AGENT_MAX_CALLS_PER_TOOL}回まで。",
                        })
                        continue

                    logger.info(f"SubAgent [{sub_task.id}] tool: {tc.name}")
                    tools_used.append(tc.name)

                    # Execute tool with parent agent_context and local call_counts
                    tool_args = {**tc.arguments, "agent_context": agent_context}
                    result = await self.tools.execute(
                        tc.name, call_counts=call_counts, **tool_args
                    )

                    call_counts[tc.name] = count + 1

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.to_content_string(),
                    })

        # Max steps exceeded — extract last useful content
        logger.warning(f"SubAgent [{sub_task.id}] exceeded {max_steps} steps")
        last_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_content = msg["content"]
                break

        return SubAgentResult(
            task_id=sub_task.id,
            description=sub_task.description,
            success=bool(tools_used),
            data=last_content or "最大ステップ超過。",
            tools_used=tools_used,
            steps_taken=max_steps,
            total_tokens=total_tokens,
            error="max_steps_exceeded" if not last_content else None,
        )
