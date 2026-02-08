from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """Represents a tool call from the LLM"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Standardized response from LLM provider"""
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    usage: Dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_final(self) -> bool:
        """True if this is a final text response (no tool calls)"""
        return self.content is not None and not self.has_tool_calls


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """Send chat completion request with optional tool definitions"""
        pass
