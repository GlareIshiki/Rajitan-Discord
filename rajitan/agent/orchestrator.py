import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import discord

from rajitan.agent.context_manager import ContextManager
from rajitan.agent.llm.base import LLMProvider, LLMResponse
from rajitan.agent.memory.prompt_integrator import MemoryPromptIntegrator
from rajitan.agent.memory.writer import AgentMemoryWriter
from rajitan.agent.prompts import AgentPromptBuilder
from rajitan.agent.tools.base import ToolRegistry, ToolResult
from rajitan.utils.logger import get_logger

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

    MAX_STEPS = 15

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        character_manager,
        conversation_tracker,
        memory_manager=None,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.character_manager = character_manager
        self.conversation_tracker = conversation_tracker
        self.memory_manager = memory_manager
        self.context_manager = ContextManager()

        # Memory subsystem
        memory_integrator = MemoryPromptIntegrator(memory_manager) if memory_manager else None
        self.memory_writer = AgentMemoryWriter(memory_manager) if memory_manager else None
        self.prompt_builder = AgentPromptBuilder(
            character_manager, conversation_tracker, memory_integrator
        )

    async def execute(self, user_message: str, context: AgentContext) -> AgentResult:
        """Execute the thinking agent loop"""
        start_time = time.time()
        tools_used: List[str] = []
        total_tokens = 0
        consecutive_errors = 0
        last_failed_tool: Optional[str] = None

        # 1. Build system prompt (structured thinking protocol)
        system_prompt = await self.prompt_builder.build_system_prompt(context)

        # 2. Build initial messages with explicit user goal
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 3. Get tool definitions (loaded once, never modified)
        tool_definitions = self.tools.get_function_definitions()

        # 4. Agent loop
        for step in range(self.MAX_STEPS):
            logger.info(f"Agent step {step + 1}/{self.MAX_STEPS}")

            # Context window management: compact if approaching limits
            if self.context_manager.should_summarize(messages):
                logger.info("Context approaching limit, compacting...")
                messages = self.context_manager.compact_context(messages)

            # Goal reminder: every 4 steps, remind LLM of original request
            if step > 0 and step % 4 == 0:
                messages.append({
                    "role": "user",
                    "content": self.prompt_builder.build_goal_reminder(user_message),
                })

            # Adaptive max_tokens and tool availability
            step_max_tokens, step_tools = self._get_step_params(
                step, tool_definitions, messages
            )

            # Call LLM
            llm_response = await self.llm.chat_completion(
                messages=messages,
                tools=step_tools,
                temperature=0.7,
                max_tokens=step_max_tokens,
            )

            if llm_response is None:
                result = AgentResult(
                    response="ごめん、うまく考えられなかった...もう一度試してみて！",
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
                elapsed = time.time() - start_time
                logger.info(
                    f"Agent completed in {step + 1} steps, {elapsed:.1f}s, "
                    f"{total_tokens} tokens, tools: {tools_used}"
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

                    # Inject agent_context into tool args
                    tool_args = {**tc.arguments, "agent_context": context}
                    result = await self.tools.execute(tc.name, **tool_args)

                    # Build tool result content with error recovery hints
                    content = self._build_tool_result_content(
                        result, tc.name, last_failed_tool, consecutive_errors
                    )

                    # Track consecutive errors
                    if not result.success:
                        consecutive_errors += 1
                        last_failed_tool = tc.name
                    else:
                        consecutive_errors = 0
                        last_failed_tool = None

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
        logger.warning(f"Agent exceeded {self.MAX_STEPS} steps")
        result = AgentResult(
            response="ごめん、処理が複雑すぎてうまくいかなかった。もう少しシンプルに伝えてくれると助かる！",
            success=False,
            steps_taken=self.MAX_STEPS,
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
        tool_definitions: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> tuple:
        """Determine max_tokens and tool availability for this step.

        - Normal steps: 1500 tokens, tools available
        - Near-end steps: 800 tokens, tools available (encourage wrapping up)
        - Final step: 800 tokens, no tools (force text response)
        """
        if step == self.MAX_STEPS - 1:
            # Absolute last step: force final answer
            messages.append({
                "role": "user",
                "content": (
                    "【システム】これが最後のステップです。"
                    "ツールを使わず、今までの結果をもとに最終回答してください。"
                ),
            })
            return 800, None
        elif step >= self.MAX_STEPS - 2:
            # Near the end: encourage conclusion
            return 800, tool_definitions if tool_definitions else None
        else:
            # Normal step: full thinking room
            return 1500, tool_definitions if tool_definitions else None

    def _build_tool_result_content(
        self,
        result: ToolResult,
        tool_name: str,
        last_failed_tool: Optional[str],
        consecutive_errors: int,
    ) -> str:
        """Build tool result content with error recovery hints when needed."""
        content = result.to_content_string()

        # If same tool failed twice in a row, add a recovery hint
        if (
            not result.success
            and tool_name == last_failed_tool
            and consecutive_errors >= 1
        ):
            content += (
                "\n\n【注意】このツールは2回連続で失敗しました。"
                "別のアプローチを試すか、ユーザーに状況を説明してください。"
            )

        return content
