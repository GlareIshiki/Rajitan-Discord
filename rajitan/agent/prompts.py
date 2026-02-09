"""
Agent system prompt builder with structured thinking protocol.

Builds the system prompt that teaches the LLM how to think before acting,
verify results, recover from errors, and respond naturally in character.
"""

from typing import TYPE_CHECKING, Optional

import discord

from rajitan.agent.workflow.schema import PromptsConfig, WorkflowConfig
from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.memory.prompt_integrator import MemoryPromptIntegrator
    from rajitan.agent.orchestrator import AgentContext

logger = get_logger("agent.prompts")


class AgentPromptBuilder:
    """Builds structured system prompts for the thinking agent"""

    def __init__(
        self,
        character_manager,
        conversation_tracker,
        memory_integrator: "MemoryPromptIntegrator" = None,
        prompts_config: Optional[PromptsConfig] = None,
    ):
        self.character_manager = character_manager
        self.conversation_tracker = conversation_tracker
        self.memory_integrator = memory_integrator
        self.prompts = prompts_config or PromptsConfig()

    async def build_system_prompt(
        self, context: "AgentContext", prompts: Optional[PromptsConfig] = None,
    ) -> str:
        """Build the complete system prompt with all sections.

        Args:
            context: Agent execution context.
            prompts: Per-execution prompts config (avoids race condition on shared instance).
        """
        p = prompts or self.prompts
        parts = []

        # Section 1: Identity
        parts.append(p.identity)

        # Section 2: Character personality (from DB)
        character_section = await self._build_character_section(context.guild_id)
        if character_section:
            parts.append(character_section)

        # Section 3-6: Prompt sections from config
        for section in (
            p.thinking_protocol,
            p.tool_usage_guide,
            p.error_recovery_guide,
            p.response_format_guide,
            p.memory_usage_guide,
        ):
            if section:
                parts.append(section)

        # Section 7: Agent memory (3-tier)
        if self.memory_integrator:
            memory_section = await self.memory_integrator.build_memory_section(context)
            if memory_section:
                parts.append(memory_section)

        # Section 8: Recent conversation context (direct Discord API)
        conversation_section = await self._build_conversation_context(
            context.message.channel
        )
        if conversation_section:
            parts.append(conversation_section)

        return "\n\n".join(parts)

    def build_step_injection(
        self,
        step: int,
        max_steps: int,
        original_request: str,
        tools_used: list,
        wf: Optional[WorkflowConfig] = None,
    ) -> str:
        """Build step-aware budget/reflection injection for the agent loop"""
        si = self.prompts.step_injection if wf is None else wf.prompts.step_injection
        al = wf.agent_loop if wf else None
        reflection_interval = al.reflection_interval if al else 3
        urgency_threshold = al.urgency_threshold if al else 3

        remaining = max_steps - step - 1
        parts = [si.normal.format(step=step + 1, max_steps=max_steps, remaining=remaining)]

        # Reflection prompt at configured interval
        if step % reflection_interval == 0 and step > 0:
            parts.append(si.reflection.format(original_request=original_request))

        # Near end: urgency
        if remaining <= urgency_threshold:
            parts.append(si.urgency)

        return "\n".join(parts)

    # --- Private section builders ---

    async def _build_character_section(self, guild_id: str) -> str:
        """Fetch character personality from DB (persona-aware)"""
        try:
            # Try persona resolution first
            if hasattr(self.character_manager, "resolve_persona"):
                persona = await self.character_manager.resolve_persona(guild_id)
                if persona and persona.system_prompt:
                    return f"## キャラクター設定\n{persona.system_prompt}"

            # Fallback: legacy character.system_prompt
            character = await self.character_manager.get_character(guild_id)
            if character and hasattr(character, "system_prompt") and character.system_prompt:
                return f"## キャラクター設定\n{character.system_prompt}"
        except Exception as e:
            logger.warning(f"Failed to get character: {e}")
        return ""

    async def _build_conversation_context(self, channel: discord.TextChannel) -> str:
        """Fetch last 15 messages directly from Discord API."""
        try:
            messages = []
            async for msg in channel.history(limit=15):
                messages.append(msg)
            messages.reverse()  # oldest first

            if messages:
                convo_lines = []
                for m in messages:
                    timestamp = m.created_at.strftime("%H:%M")
                    content = m.content[:200] if m.content else ""
                    if m.attachments:
                        attachment_info = " ".join(
                            f"[添付: {a.filename} {a.url}]" for a in m.attachments
                        )
                        content = f"{content} {attachment_info}".strip()
                    if not content:
                        content = "(embed)"
                    convo_lines.append(
                        f"[{timestamp}] {m.author.display_name}: {content}"
                    )
                if convo_lines:
                    return "## 最近の会話（直近15件）\n" + "\n".join(convo_lines)
        except Exception as e:
            logger.warning(f"Failed to fetch Discord history: {e}")
        return ""
