import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import discord

from rajitan.agent.llm.base import LLMProvider, LLMResponse
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


class AgentOrchestrator:
    """Main agent loop — plans, executes tools, verifies, and loops"""

    MAX_STEPS = 15

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        character_manager,
        conversation_tracker,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.character_manager = character_manager
        self.conversation_tracker = conversation_tracker

    async def execute(self, user_message: str, context: AgentContext) -> AgentResult:
        """Execute the agent loop"""
        start_time = time.time()
        tools_used: List[str] = []
        total_tokens = 0

        # 1. Build system prompt (immutable prefix)
        system_prompt = await self._build_system_prompt(context)

        # 2. Build initial messages (append-only)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 3. Get tool definitions (loaded once at start, never modified)
        tool_definitions = self.tools.get_function_definitions()

        # 4. Agent loop
        for step in range(self.MAX_STEPS):
            logger.info(f"Agent step {step + 1}/{self.MAX_STEPS}")

            # Call LLM
            llm_response = await self.llm.chat_completion(
                messages=messages,
                tools=tool_definitions if tool_definitions else None,
                temperature=0.7,
                max_tokens=1000,
            )

            if llm_response is None:
                return AgentResult(
                    response="ごめん、うまく考えられなかった...もう一度試してみて！",
                    success=False,
                    steps_taken=step + 1,
                    tools_used=tools_used,
                    total_tokens=total_tokens,
                )

            total_tokens += llm_response.usage.get("total_tokens", 0)

            # Case 1: Final text response (no tool calls)
            if llm_response.is_final:
                elapsed = time.time() - start_time
                logger.info(
                    f"Agent completed in {step + 1} steps, {elapsed:.1f}s, "
                    f"{total_tokens} tokens, tools: {tools_used}"
                )
                return AgentResult(
                    response=llm_response.content,
                    success=True,
                    steps_taken=step + 1,
                    tools_used=tools_used,
                    total_tokens=total_tokens,
                )

            # Case 2: Tool calls
            if llm_response.has_tool_calls:
                # Append assistant message with tool calls to context
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": llm_response.content}
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

                # Execute each tool call and append results
                for tc in llm_response.tool_calls:
                    logger.info(f"Executing tool: {tc.name} with args: {tc.arguments}")
                    tools_used.append(tc.name)

                    # Inject agent_context into tool args
                    tool_args = {**tc.arguments, "agent_context": context}
                    result = await self.tools.execute(tc.name, **tool_args)

                    # Append tool result to context (append-only, errors preserved)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result.to_content_string(),
                        }
                    )

            # Case 3: Response with content but also tool calls
            # (handled by Case 2 — content is preserved in assistant_msg)

            # Case 4: Neither content nor tool calls (shouldn't happen)
            elif not llm_response.content and not llm_response.has_tool_calls:
                logger.warning("LLM returned empty response")
                messages.append(
                    {"role": "assistant", "content": ""}
                )

        # Max steps exceeded
        logger.warning(f"Agent exceeded {self.MAX_STEPS} steps")
        return AgentResult(
            response="ごめん、処理が複雑すぎてうまくいかなかった。もう少しシンプルに伝えてくれると助かる！",
            success=False,
            steps_taken=self.MAX_STEPS,
            tools_used=tools_used,
            total_tokens=total_tokens,
        )

    async def _build_system_prompt(self, context: AgentContext) -> str:
        """Build immutable system prompt"""
        parts = []

        # Immutable prefix
        parts.append("あなたはDiscordサーバーで活動するAIアシスタント「らじたん」です。")
        parts.append("ラジオDJのようなフレンドリーな口調で、ユーザーと楽しくやり取りしてください。")

        # Character personality
        try:
            character = await self.character_manager.get_character(context.guild_id)
            if character and hasattr(character, "system_prompt") and character.system_prompt:
                parts.append(f"\n## キャラクター設定\n{character.system_prompt}")
        except Exception as e:
            logger.warning(f"Failed to get character: {e}")

        # Tool usage instructions
        parts.append("\n## ツールの使い方")
        parts.append("利用可能なツールを使って、ユーザーのリクエストに応えてください。")
        parts.append("複数のツールを組み合わせて、段階的にタスクを完了できます。")
        parts.append("ツールを使わなくても答えられる質問には、直接テキストで回答してください。")
        parts.append("ツールの実行結果を確認してから、次のアクションを決定してください。")
        parts.append("最終的にユーザーへの応答をテキストで返してください。")

        # Recent conversation context
        try:
            recent_msgs = await self.conversation_tracker.get_recent_conversation(
                context.channel_id, duration_minutes=30
            )
            if recent_msgs:
                convo_lines = []
                for m in recent_msgs[-10:]:  # Last 10 messages for context
                    convo_lines.append(f"{m.username}: {m.content[:200]}")
                parts.append(f"\n## 最近の会話\n" + "\n".join(convo_lines))
        except Exception as e:
            logger.warning(f"Failed to get recent conversation: {e}")

        return "\n".join(parts)
