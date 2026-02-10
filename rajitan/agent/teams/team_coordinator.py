"""
AgentTeamCoordinator — Top-level orchestrator for Agent Teams.

Manages the full lifecycle: plan → task graph → wave execution → synthesis.
Falls back to single-agent on any failure.
"""

import asyncio
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.teams.leader import TeamLeader
from rajitan.agent.teams.mailbox import TeamMailbox
from rajitan.agent.teams.models import (
    AgentTeamsResult,
    TeamRole,
    TeamTask,
    TeammateResult,
)
from rajitan.agent.teams.task_graph import CyclicDependencyError, TaskGraph
from rajitan.agent.teams.teammate import TeammateRunner
from rajitan.agent.tools.base import ToolRegistry
from rajitan.agent.workflow.schema import AgentTeamsConfig, WorkflowConfig
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.orchestrator import AgentContext
    from rajitan.agent.workflow.execution_log import ExecutionLogCollector

logger = get_logger("agent.teams.coordinator")


class AgentTeamCoordinator:
    """Orchestrates role-based collaborative multi-agent execution."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentTeamsConfig,
        character_manager=None,
        execution_log: "ExecutionLogCollector" = None,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.cfg = config
        self.character_manager = character_manager
        self._exec_log = execution_log
        self.leader = TeamLeader(llm_provider, config)

    async def try_execute(
        self,
        user_message: str,
        context: "AgentContext",
        wf: WorkflowConfig,
        exec_id: str = "",
        llm_provider: LLMProvider = None,
    ) -> AgentTeamsResult:
        """Attempt Agent Teams execution.

        Returns AgentTeamsResult with used_teams=False if not suitable.
        """
        overall_start = time.time()

        # Step 1: Leader plans
        await self._emit(exec_id, context, "agent_teams_plan_start")

        available_tools = self.tools.list_tools()
        tool_descriptions = self._get_tool_descriptions()

        effective_llm = llm_provider or self.llm

        try:
            plan = await self.leader.plan(user_message, available_tools, tool_descriptions, llm_override=effective_llm)
        except Exception as e:
            logger.error(f"Agent Teams plan failed: {e}")
            await self._emit(exec_id, context, "agent_teams_plan_skip", content=str(e))
            return AgentTeamsResult(used_teams=False, plan_reasoning=f"plan_error: {e}")

        if not plan.should_use_teams:
            logger.info(f"Agent Teams: not needed ({plan.reasoning})")
            await self._emit(exec_id, context, "agent_teams_plan_skip", content=plan.reasoning)
            return AgentTeamsResult(used_teams=False, plan_reasoning=plan.reasoning)

        # Step 2: Build TaskGraph
        try:
            task_graph = TaskGraph(plan.tasks)
        except CyclicDependencyError as e:
            logger.warning(f"Agent Teams: cyclic dependency: {e}")
            await self._emit(exec_id, context, "agent_teams_plan_skip", content=str(e))
            return AgentTeamsResult(used_teams=False, plan_reasoning=f"cyclic: {e}")

        max_wave = task_graph.get_max_wave()
        if max_wave >= self.cfg.max_waves:
            logger.warning(f"Agent Teams: too many waves ({max_wave + 1} > {self.cfg.max_waves})")
            return AgentTeamsResult(used_teams=False, plan_reasoning="too_many_waves")

        roles_map: Dict[str, TeamRole] = {r.role_id: r for r in plan.roles}
        mailbox = TeamMailbox()

        logger.info(
            f"Agent Teams: {len(plan.roles)} roles, {len(plan.tasks)} tasks, "
            f"{max_wave + 1} waves — {plan.reasoning[:60]}"
        )
        await self._emit(
            exec_id, context, "agent_teams_plan_done",
            content=f"{len(plan.roles)} roles, {len(plan.tasks)} tasks, {max_wave + 1} waves",
        )

        # Step 3: Execute waves
        all_results: List[TeammateResult] = []
        total_tokens = 0

        for wave in range(max_wave + 1):
            # Check overall timeout
            elapsed = time.time() - overall_start
            if elapsed > self.cfg.overall_timeout_seconds:
                logger.warning(f"Agent Teams: overall timeout at wave {wave}")
                break

            wave_results = await self._execute_wave(
                wave, task_graph, mailbox, roles_map, context, exec_id,
                llm_provider=effective_llm,
            )
            all_results.extend(wave_results)
            for wr in wave_results:
                total_tokens += wr.total_tokens

        waves_executed = min(max_wave + 1, len(range(max_wave + 1)))

        # Step 4: Synthesize
        await self._emit(exec_id, context, "agent_teams_synthesize_start")

        character_prompt = await self._get_character_prompt(context.guild_id)
        all_messages = mailbox.read_all()

        try:
            final_response = await self.leader.synthesize(
                user_message=user_message,
                teammate_results=all_results,
                messages=all_messages,
                character_prompt=character_prompt,
                llm_override=effective_llm,
            )
        except Exception as e:
            logger.error(f"Agent Teams synthesis failed: {e}")
            return AgentTeamsResult(
                used_teams=False,
                teammate_results=all_results,
                total_tokens=total_tokens,
                plan_reasoning="synthesis_failed",
            )

        if not final_response:
            logger.warning("Agent Teams: synthesis returned empty")
            return AgentTeamsResult(
                used_teams=False,
                teammate_results=all_results,
                total_tokens=total_tokens,
                plan_reasoning="synthesis_empty",
            )

        elapsed_total = time.time() - overall_start
        logger.info(
            f"Agent Teams: completed in {elapsed_total:.1f}s, "
            f"{waves_executed} waves, {len(all_results)} task results, "
            f"{total_tokens} tokens, {mailbox.message_count} messages"
        )
        await self._emit(
            exec_id, context, "agent_teams_complete",
            content=f"{elapsed_total:.1f}s, {total_tokens} tokens, {waves_executed} waves",
        )

        return AgentTeamsResult(
            used_teams=True,
            response=final_response,
            teammate_results=all_results,
            total_tokens=total_tokens,
            plan_reasoning=plan.reasoning,
            waves_executed=waves_executed,
        )

    async def _execute_wave(
        self,
        wave: int,
        task_graph: TaskGraph,
        mailbox: TeamMailbox,
        roles_map: Dict[str, TeamRole],
        context: "AgentContext",
        exec_id: str,
        llm_provider: LLMProvider = None,
    ) -> List[TeammateResult]:
        """Execute all tasks in a wave.

        Groups tasks by role, spawns one TeammateRunner per role.
        Same-role tasks are handled sequentially via self-claim.
        Different roles run in parallel.
        """
        wave_tasks = task_graph.get_wave_tasks(wave)
        if not wave_tasks:
            return []

        logger.info(
            f"Agent Teams wave {wave}: {len(wave_tasks)} tasks — "
            f"{[t.task_id for t in wave_tasks]}"
        )
        await self._emit(
            exec_id, context, "agent_teams_wave_start",
            content=f"Wave {wave}: {len(wave_tasks)} tasks",
        )

        # Group tasks by role — one runner per role
        role_tasks: Dict[str, List[TeamTask]] = defaultdict(list)
        for task in wave_tasks:
            role_tasks[task.assigned_role].append(task)

        # Create runners and launch in parallel
        async def _run_teammate(role_id: str, tasks: List[TeamTask]):
            role = roles_map.get(role_id)
            if not role:
                logger.warning(f"Unknown role: {role_id}")
                return []

            teammate_id = f"{role_id}_1"
            runner = TeammateRunner(
                llm_provider or self.llm, self.tools, self.cfg, task_graph, mailbox,
            )

            await self._emit(
                exec_id, context, "agent_teams_teammate_start",
                content=f"{teammate_id}: {tasks[0].task_id}",
            )

            try:
                results = await asyncio.wait_for(
                    runner.run(
                        teammate_id=teammate_id,
                        role=role,
                        initial_task=tasks[0],
                        agent_context=context,
                        all_roles=roles_map,
                        exec_id=exec_id,
                    ),
                    timeout=self.cfg.teammate_timeout_seconds,
                )

                for r in results:
                    await self._emit(
                        exec_id, context, "agent_teams_teammate_done",
                        content=f"{r.teammate_id}/{r.task_id}: {'OK' if r.success else 'FAIL'}",
                    )
                return results

            except asyncio.TimeoutError:
                logger.warning(f"Teammate [{teammate_id}] timed out")
                # Mark uncompleted tasks as failed
                for t in tasks:
                    if t.status == "in_progress" and t.claimed_by == teammate_id:
                        await task_graph.fail_task(t.task_id, "timeout")
                return [TeammateResult(
                    teammate_id=teammate_id,
                    task_id=tasks[0].task_id,
                    role_id=role_id,
                    success=False,
                    error=f"タイムアウト ({self.cfg.teammate_timeout_seconds}秒)",
                )]
            except Exception as e:
                logger.error(f"Teammate [{teammate_id}] failed: {e}")
                return [TeammateResult(
                    teammate_id=f"{role_id}_1",
                    task_id=tasks[0].task_id,
                    role_id=role_id,
                    success=False,
                    error=str(e),
                )]

        # Run all roles in parallel
        coroutines = [
            _run_teammate(role_id, tasks)
            for role_id, tasks in role_tasks.items()
        ]
        gathered = await asyncio.gather(*coroutines)

        # Flatten results
        all_wave_results: List[TeammateResult] = []
        for result_list in gathered:
            all_wave_results.extend(result_list)

        await self._emit(
            exec_id, context, "agent_teams_wave_done",
            content=f"Wave {wave}: {len(all_wave_results)} results",
        )

        return all_wave_results

    def _get_tool_descriptions(self) -> Dict[str, str]:
        """Get tool descriptions for the leader's planning prompt."""
        descriptions = {}
        for td in self.tools.get_function_definitions():
            name = td["function"]["name"]
            desc = td["function"].get("description", "")
            descriptions[name] = desc
        return descriptions

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
        """Emit an execution log event."""
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
            logger.debug(f"Failed to emit teams event: {e}")
