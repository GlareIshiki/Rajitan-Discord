"""
Context window management for the agent system.

Prevents context window exhaustion by estimating token usage
and compacting older exchanges when approaching limits.
"""

import json
from typing import Any, Dict, List, Optional

from rajitan.agent.workflow.schema import ContextConfig
from rajitan.utils.logger import get_logger

logger = get_logger("agent.context_manager")


class ContextManager:
    """Manages the agent's conversation context to prevent window exhaustion"""

    def __init__(self, context_config: Optional[ContextConfig] = None):
        self.cfg = context_config or ContextConfig()

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Rough token estimation.

        For Japanese text, roughly 1 token ≈ 2-3 characters.
        Uses chars_per_token from config as estimate.
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content") or ""
            total_chars += len(content)
            # Account for tool_calls JSON overhead
            if "tool_calls" in msg:
                total_chars += len(
                    json.dumps(msg["tool_calls"], ensure_ascii=False)
                )
        return total_chars // self.cfg.chars_per_token

    def should_summarize(self, messages: List[Dict[str, Any]]) -> bool:
        """Check if context is getting too large"""
        return self.estimate_tokens(messages) > self.cfg.warning_threshold

    def compact_context(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Compact older context while preserving critical messages.

        Strategy:
        1. Always keep system message (index 0)
        2. Always keep original user message (index 1)
        3. Summarize middle tool exchanges into a compact note
        4. Keep the last N messages intact
        """
        keep_last = self.cfg.keep_last_n_exchanges

        # Not enough messages to compact
        if len(messages) <= keep_last + 2:
            return messages

        system_msg = messages[0]
        user_msg = messages[1]
        middle = messages[2:-keep_last]
        recent = messages[-keep_last:]

        # Build a compact summary of middle exchanges
        summary_parts = []
        for msg in middle:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "assistant" and content:
                summary_parts.append(f"アシスタント: {content[:100]}")
            elif role == "tool":
                summary_parts.append(f"ツール結果: {content[:150]}")

        # Keep only the last N entries to stay compact
        summary_text = "【これまでの経過】\n" + "\n".join(
            summary_parts[-self.cfg.summary_keep_entries:]
        )

        before_count = len(messages)
        compacted = [
            system_msg,
            user_msg,
            {"role": "assistant", "content": summary_text},
            *recent,
        ]

        logger.info(
            f"Context compacted: {before_count} messages → {len(compacted)} messages "
            f"(estimated {self.estimate_tokens(compacted)} tokens)"
        )
        return compacted
