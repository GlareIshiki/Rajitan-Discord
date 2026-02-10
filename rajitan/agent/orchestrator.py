import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord

from rajitan.agent.context_manager import ContextManager
from rajitan.agent.llm.base import LLMProvider, LLMResponse
from rajitan.agent.memory.prompt_integrator import MemoryPromptIntegrator
from rajitan.agent.memory.writer import AgentMemoryWriter
from rajitan.agent.prompts import AgentPromptBuilder
from rajitan.agent.tools.base import ToolRegistry, ToolResult
from rajitan.agent.workflow.schema import WorkflowConfig
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.workflow.execution_log import ExecutionLogCollector
    from rajitan.agent.workflow.loader import WorkflowLoader

logger = get_logger("agent.orchestrator")


@dataclass
class AgentContext:
    """Context passed to the agent for each execution"""
    guild_id: str
    channel_id: str
    user_id: str
    username: str
    message: discord.Message


@dataclass
class AgentResult:
    """Result of agent execution"""
    response: str
    success: bool
    steps_taken: int = 0
    tools_used: List[str] = field(default_factory=list)
    total_tokens: int = 0
    goal: Optional[str] = None


class AgentOrchestrator:
    """Thinking agent loop — understands, plans, executes, verifies, and responds"""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        character_manager,
        conversation_tracker,
        memory_manager=None,
        workflow_loader: "WorkflowLoader" = None,
        execution_log: "ExecutionLogCollector" = None,
        team_coordinator=None,
        agent_teams_coordinator=None,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.character_manager = character_manager
        self.conversation_tracker = conversation_tracker
        self.memory_manager = memory_manager
        self._wf_loader = workflow_loader
        self._exec_log = execution_log
        self.team_coordinator = team_coordinator
        self.agent_teams_coordinator = agent_teams_coordinator

        # Context manager uses base workflow config
        wf = self._get_base_wf()
        self.context_manager = ContextManager(context_config=wf.context)

        # Memory subsystem
        memory_integrator = MemoryPromptIntegrator(memory_manager) if memory_manager else None
        self.memory_writer = AgentMemoryWriter(memory_manager) if memory_manager else None
        self.prompt_builder = AgentPromptBuilder(
            character_manager, conversation_tracker, memory_integrator,
            prompts_config=wf.prompts,
        )

    def _get_base_wf(self) -> WorkflowConfig:
        if self._wf_loader:
            return self._wf_loader.base_config
        return WorkflowConfig()

    async def execute(self, user_message: str, context: AgentContext) -> AgentResult:
        """Execute the thinking agent loop"""
        start_time = time.time()
        tools_used: List[str] = []
        total_tokens = 0
        consecutive_errors = 0
        last_failed_tool: Optional[str] = None
        tool_call_history: List[str] = []

        # Execution log
        exec_id = self._exec_log.new_execution_id() if self._exec_log else ""

        # Get effective workflow for this user (base + overlay)
        if self._wf_loader:
            wf = await self._wf_loader.get_effective_config(context.guild_id, context.user_id)
        else:
            wf = WorkflowConfig()

        max_steps = wf.agent_loop.max_steps

        # Agent Teams mode: role-based collaboration with dependency graph
        if self.agent_teams_coordinator and wf.agent_teams.enabled:
            from rajitan.agent.teams.models import AgentTeamsResult
            teams_result = await self.agent_teams_coordinator.try_execute(
                user_message=user_message,
                context=context,
                wf=wf,
                exec_id=exec_id,
            )
            if teams_result.used_teams and teams_result.response:
                logger.info("Agent Teams produced result, skipping single-agent loop")
                all_tools = []
                for tr in teams_result.teammate_results:
                    all_tools.extend(tr.tools_used)
                result = AgentResult(
                    response=teams_result.response,
                    success=True,
                    steps_taken=0,
                    tools_used=all_tools,
                    total_tokens=teams_result.total_tokens,
                    goal=user_message,
                )
                if self.memory_writer:
                    await self.memory_writer.process_result(result, context)
                return result

        # Team mode: decompose → parallel sub-agents → synthesize
        if self.team_coordinator and wf.team.enabled:
            from rajitan.agent.team.coordinator import TeamResult
            team_result = await self.team_coordinator.try_team_execute(
                user_message=user_message,
                context=context,
                wf=wf,
                exec_id=exec_id,
            )
            if team_result.used_team and team_result.response:
                logger.info("Team mode produced result, skipping single-agent loop")
                all_tools = []
                for sr in team_result.sub_results:
                    all_tools.extend(sr.tools_used)
                result = AgentResult(
                    response=team_result.response,
                    success=True,
                    steps_taken=0,
                    tools_used=all_tools,
                    total_tokens=team_result.total_tokens,
                    goal=user_message,
                )
                if self.memory_writer:
                    await self.memory_writer.process_result(result, context)
                return result

        # Determine thinking mode based on message complexity
        use_thinking = self._looks_complex(user_message, wf)
        logger.info(f"Agent mode: {'thinking' if use_thinking else 'non-thinking'} for: {user_message[:40]}")

        # Emit start event
        await self._emit(
            "start", exec_id, context,
            content=user_message[:200], max_steps=max_steps, thinking=use_thinking,
        )

        # Reset per-execution tool call counts and apply per-user tool config
        self.tools.reset_call_counts()
        disabled_tools = self.tools.apply_per_execution_config(wf.tools)

        # 1. Build system prompt (structured thinking protocol)
        system_prompt = await self.prompt_builder.build_system_prompt(context, prompts=wf.prompts)

        # 2. Build initial messages with explicit user goal
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 3. Get tool definitions (filtered by per-user disabled list)
        tool_definitions = self.tools.get_function_definitions(exclude=disabled_tools)

        # 4. Agent loop
        for step in range(max_steps):
            logger.info(f"Agent step {step + 1}/{max_steps}")
            await self._emit("step", exec_id, context, step=step, max_steps=max_steps)

            # Context window management: compact if approaching limits
            if self.context_manager.should_summarize(messages):
                logger.info("Context approaching limit, compacting...")
                messages = self.context_manager.compact_context(messages)

            # Step-aware context injection: budget + reflection + planning
            if step == max_steps - 1:
                # Final step: inject final_step prompt only (force text answer)
                messages.append({
                    "role": "user",
                    "content": wf.prompts.step_injection.final_step,
                })
            elif step == 0 and self._looks_complex(user_message, wf):
                messages.append({
                    "role": "user",
                    "content": wf.prompts.step_injection.first_step.format(
                        max_steps=max_steps,
                    ),
                })
            elif step > 0:
                step_injection = self.prompt_builder.build_step_injection(
                    step=step,
                    max_steps=max_steps,
                    original_request=user_message,
                    tools_used=tools_used,
                    wf=wf,
                )
                if step_injection:
                    messages.append({"role": "user", "content": step_injection})

            # Adaptive max_tokens and tool availability
            step_max_tokens, step_tools = self._get_step_params(
                step, max_steps, tool_definitions, wf
            )

            # Call LLM
            llm_response = await self.llm.chat_completion(
                messages=messages,
                tools=step_tools,
                temperature=wf.agent_loop.temperature,
                max_tokens=step_max_tokens,
                thinking=use_thinking,
            )

            if llm_response is None:
                await self._emit("error", exec_id, context, step=step, content="LLM returned None")
                result = AgentResult(
                    response=wf.prompts.messages.get("llm_failure", ""),
                    success=False,
                    steps_taken=step + 1,
                    tools_used=tools_used,
                    total_tokens=total_tokens,
                    goal=user_message,
                )
                if self.memory_writer:
                    await self.memory_writer.process_result(result, context)
                return result

            total_tokens += llm_response.usage.get("total_tokens", 0)

            # Case 1: Final text response (no tool calls)
            if llm_response.is_final:
                # Nudge: if step 0 returned text-only without using any tools,
                # and the request isn't a simple greeting, retry once with a hint.
                if step == 0 and not tools_used and not self._is_light(user_message, wf):
                    logger.info("Step 0 text-only for non-trivial request, nudging tool usage")
                    messages.append({"role": "assistant", "content": llm_response.content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "【システム】あなたにはツールが利用可能です。"
                            "ユーザーのリクエストにツールを使って対応できませんか？"
                            "過去の会話で失敗していても、状況は変わっている可能性があります。"
                            "ツールが必要なら実行してください。不要なら先ほどの回答をそのまま返してください。"
                        ),
                    })
                    continue

                elapsed = time.time() - start_time
                logger.info(
                    f"Agent completed in {step + 1} steps, {elapsed:.1f}s, "
                    f"{total_tokens} tokens, tools: {tools_used}"
                )
                await self._emit(
                    "final", exec_id, context,
                    step=step, tokens=total_tokens,
                    content=(llm_response.content or "")[:200],
                )
                result = AgentResult(
                    response=llm_response.content,
                    success=True,
                    steps_taken=step + 1,
                    tools_used=tools_used,
                    total_tokens=total_tokens,
                    goal=user_message,
                )
                if self.memory_writer:
                    await self.memory_writer.process_result(result, context)
                return result

            # Case 2: Tool calls
            if llm_response.has_tool_calls:
                # Append assistant message with tool calls to context
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
                            "arguments": json.dumps(
                                tc.arguments, ensure_ascii=False
                            ),
                        },
                    }
                    for tc in llm_response.tool_calls
                ]
                messages.append(assistant_msg)

                # Execute each tool call and append results
                for tc in llm_response.tool_calls:
                    logger.info(
                        f"Executing tool: {tc.name} with args: {tc.arguments}"
                    )
                    tools_used.append(tc.name)
                    await self._emit(
                        "tool_call", exec_id, context,
                        step=step, tool_name=tc.name, tool_args=tc.arguments,
                    )

                    # Inject agent_context into tool args
                    tool_args = {**tc.arguments, "agent_context": context}
                    result = await self.tools.execute(tc.name, disabled=disabled_tools, **tool_args)

                    await self._emit(
                        "tool_result", exec_id, context,
                        step=step, tool_name=tc.name, tool_success=result.success,
                        content=(result.to_content_string() or "")[:200],
                    )

                    # Build tool result content with error recovery hints
                    content = self._build_tool_result_content(
                        result, tc.name, last_failed_tool, consecutive_errors, wf
                    )

                    # Track consecutive errors
                    if not result.success:
                        consecutive_errors += 1
                        last_failed_tool = tc.name
                    else:
                        consecutive_errors = 0
                        last_failed_tool = None

                    # Track consecutive same-tool usage and warn
                    tool_call_history.append(tc.name)
                    consecutive_same = 0
                    for past in reversed(tool_call_history):
                        if past == tc.name:
                            consecutive_same += 1
                        else:
                            break
                    if consecutive_same >= 2 and result.success:
                        warning_tpl = wf.prompts.messages.get(
                            "consecutive_tool_warning",
                            "\n\n【注意】{tool_name}を{count}回連続で使用中。"
                        )
                        content += warning_tpl.format(
                            tool_name=tc.name, count=consecutive_same
                        )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content,
                    })

            # Case 3: Neither content nor tool calls (shouldn't happen)
            elif not llm_response.content and not llm_response.has_tool_calls:
                logger.warning("LLM returned empty response")
                messages.append({"role": "assistant", "content": ""})

        # Max steps exceeded
        logger.warning(f"Agent exceeded {max_steps} steps")
        await self._emit("error", exec_id, context, step=max_steps - 1, content="Max steps exceeded")
        result = AgentResult(
            response=wf.prompts.messages.get("max_steps_exceeded", ""),
            success=False,
            steps_taken=max_steps,
            tools_used=tools_used,
            total_tokens=total_tokens,
            goal=user_message,
        )
        if self.memory_writer:
            await self.memory_writer.process_result(result, context)
        return result

    def _get_step_params(
        self,
        step: int,
        max_steps: int,
        tool_definitions: List[Dict[str, Any]],
        wf: WorkflowConfig,
    ) -> tuple:
        """Determine max_tokens and tool availability for this step (pure, no side effects)."""
        sp = wf.agent_loop

        if step == max_steps - 1:
            return sp.step_params_final.max_tokens, None if not sp.step_params_final.tools_enabled else (tool_definitions or None)
        elif step >= max_steps - 2:
            p = sp.step_params_near_end
            return p.max_tokens, tool_definitions if (p.tools_enabled and tool_definitions) else None
        else:
            p = sp.step_params_normal
            return p.max_tokens, tool_definitions if (p.tools_enabled and tool_definitions) else None

    def _is_light(self, user_message: str, wf: WorkflowConfig = None) -> bool:
        """Check if the message is a simple greeting/reaction that doesn't need tools."""
        if wf is None:
            wf = self._get_base_wf()
        if len(user_message) < wf.complexity.min_length:
            return True
        if any(p in user_message for p in wf.complexity.light_patterns):
            return True
        return False

    def _looks_complex(self, user_message: str, wf: WorkflowConfig = None) -> bool:
        """Heuristic: does this request likely need multi-step tool use?"""
        if wf is None:
            wf = self._get_base_wf()
        if len(user_message) < wf.complexity.min_length:
            return False
        if any(p in user_message for p in wf.complexity.light_patterns):
            return False
        return True

    async def _emit(self, event_type: str, exec_id: str, context: AgentContext, **kwargs) -> None:
        """Emit an execution log event (no-op if no collector)."""
        if not self._exec_log:
            return
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

    def _build_tool_result_content(
        self,
        result: ToolResult,
        tool_name: str,
        last_failed_tool: Optional[str],
        consecutive_errors: int,
        wf: WorkflowConfig,
    ) -> str:
        """Build tool result content with verification nudges and error recovery."""
        content = result.to_content_string()

        # Success: verification nudge
        if result.success:
            content += wf.prompts.messages.get("verification_nudge", "")

        # If same tool failed twice in a row, add a recovery hint
        if (
            not result.success
            and tool_name == last_failed_tool
            and consecutive_errors >= 1
        ):
            content += wf.prompts.messages.get("double_failure_warning", "")

        return content
