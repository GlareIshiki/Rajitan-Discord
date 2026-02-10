"""
TeamCoordinator — Multi-agent team orchestration.

Receives a user request, decides whether team mode is beneficial,
decomposes into sub-tasks, runs sub-agents in parallel, and synthesizes results.
Falls back to single-agent mode when team mode is not warranted.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.team.planner import TaskPlanner
from rajitan.agent.team.sub_agent import SubAgentRunner, SubAgentResult
from rajitan.agent.tools.base import ToolRegistry
from rajitan.agent.workflow.schema import TeamConfig, WorkflowConfig
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.orchestrator import AgentContext
    from rajitan.agent.workflow.execution_log import ExecutionLogCollector

logger = get_logger("agent.team.coordinator")


@dataclass
class TeamResult:
    """Result from team execution."""
    used_team: bool
    response: Optional[str] = None
    sub_results: List[SubAgentResult] = field(default_factory=list)
    total_tokens: int = 0
    decomposition_reasoning: str = ""


class TeamCoordinator:
    """Orchestrates multi-agent team execution."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        team_config: TeamConfig,
        character_manager=None,
        execution_log: "ExecutionLogCollector" = None,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.cfg = team_config
        self.character_manager = character_manager
        self._exec_log = execution_log

        self.planner = TaskPlanner(llm_provider, team_config)

    async def try_team_execute(
        self,
        user_message: str,
        context: "AgentContext",
        wf: WorkflowConfig,
        exec_id: str = "",
    ) -> TeamResult:
        """Attempt team execution.

        Returns TeamResult with used_team=False if single-agent is preferred.
        """
        if not self.cfg.enabled:
            return TeamResult(used_team=False)

        start_time = time.time()
        total_tokens = 0

        available_tools = self.tools.list_tools()

        # Step 1: Decompose
        logger.info(f"Team: decomposing: {user_message[:60]}...")
        await self._emit(exec_id, context, "team_decompose_start")

        decomposition = await self.planner.decompose(user_message, available_tools)

        if not decomposition.should_use_team:
            logger.info(f"Team: single-agent preferred ({decomposition.reasoning})")
            await self._emit(exec_id, context, "team_skip", content=decomposition.reasoning)
            return TeamResult(
                used_team=False,
                decomposition_reasoning=decomposition.reasoning,
            )

        logger.info(
            f"Team: {len(decomposition.sub_tasks)} sub-tasks: "
            f"{[st.id for st in decomposition.sub_tasks]}"
        )
        await self._emit(
            exec_id, context, "team_decompose_done",
            content=f"{len(decomposition.sub_tasks)} sub-tasks",
        )

        # Step 2: Run sub-agents in parallel
        runner = SubAgentRunner(self.llm, self.tools, self.cfg)

        async def _run_with_timeout(sub_task):
            try:
                return await asyncio.wait_for(
                    runner.execute(sub_task, context, exec_id),
                    timeout=self.cfg.sub_agent_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(f"SubAgent [{sub_task.id}] timed out")
                return SubAgentResult(
                    task_id=sub_task.id,
                    description=sub_task.description,
                    success=False,
                    error=f"タイムアウト ({self.cfg.sub_agent_timeout_seconds}秒)",
                )
            except Exception as e:
                logger.error(f"SubAgent [{sub_task.id}] failed: {e}")
                return SubAgentResult(
                    task_id=sub_task.id,
                    description=sub_task.description,
                    success=False,
                    error=str(e),
                )

        await self._emit(exec_id, context, "team_parallel_start")

        sub_results: List[SubAgentResult] = await asyncio.gather(
            *[_run_with_timeout(st) for st in decomposition.sub_tasks]
        )

        for sr in sub_results:
            total_tokens += sr.total_tokens
            await self._emit(
                exec_id, context, "team_sub_agent_done",
                content=f"{sr.task_id}: {'OK' if sr.success else 'FAIL'} ({sr.steps_taken} steps)",
            )

        elapsed_parallel = time.time() - start_time
        logger.info(f"Team: all sub-agents done in {elapsed_parallel:.1f}s")

        # Step 3: Synthesize
        await self._emit(exec_id, context, "team_synthesize_start")

        character_prompt = await self._get_character_prompt(context.guild_id)

        results_for_synthesis = [
            {
                "task_id": sr.task_id,
                "description": sr.description,
                "success": sr.success,
                "data": sr.data or sr.error or "(なし)",
                "tools_used": sr.tools_used,
            }
            for sr in sub_results
        ]

        final_response = await self.planner.synthesize(
            user_message=user_message,
            sub_agent_results=results_for_synthesis,
            character_prompt=character_prompt,
        )

        if final_response is None:
            logger.warning("Team: synthesis failed, falling back to single-agent")
            return TeamResult(
                used_team=False,
                sub_results=sub_results,
                total_tokens=total_tokens,
                decomposition_reasoning="synthesis_failed",
            )

        elapsed_total = time.time() - start_time
        all_tools = []
        for sr in sub_results:
            all_tools.extend(sr.tools_used)

        logger.info(
            f"Team: completed in {elapsed_total:.1f}s, "
            f"{len(sub_results)} sub-agents, {total_tokens} tokens, tools: {all_tools}"
        )
        await self._emit(
            exec_id, context, "team_complete",
            content=f"{elapsed_total:.1f}s, {total_tokens} tokens",
        )

        return TeamResult(
            used_team=True,
            response=final_response,
            sub_results=sub_results,
            total_tokens=total_tokens,
            decomposition_reasoning=decomposition.reasoning,
        )

    async def _get_character_prompt(self, guild_id: str) -> str:
        """Get character personality for synthesis."""
        if not self.character_manager:
            return ""
        try:
            if hasattr(self.character_manager, "resolve_persona"):
                persona = await self.character_manager.resolve_persona(guild_id)
                if persona and persona.system_prompt:
                    return persona.system_prompt
            character = await self.character_manager.get_character(guild_id)
            if character and hasattr(character, "system_prompt") and character.system_prompt:
                return character.system_prompt
        except Exception as e:
            logger.warning(f"Failed to get character for synthesis: {e}")
        return ""

    async def _emit(
        self, exec_id: str, context: "AgentContext", event_type: str, **kwargs
    ) -> None:
        """Emit a team-specific execution log event."""
        if not self._exec_log:
            return
        try:
            from rajitan.agent.workflow.execution_log import ExecutionEvent
            event = ExecutionEvent(
                event_type=event_type,
                execution_id=exec_id,
                guild_id=context.guild_id,
                channel_id=context.channel_id,
                user_id=context.user_id,
                **kwargs,
            )
            await self._exec_log.emit(event)
        except Exception as e:
            logger.debug(f"Failed to emit team event: {e}")
