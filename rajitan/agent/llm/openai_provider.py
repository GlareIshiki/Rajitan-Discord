import json
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from rajitan.agent.llm.base import LLMProvider, LLMResponse, ToolCall
from rajitan.utils.decorators import handle_async_errors, with_retries
from rajitan.utils.logger import get_logger

logger = get_logger("agent.llm.openai")


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider with function calling support"""

    def __init__(self, client: AsyncOpenAI, model: str = "gpt-4o-mini"):
        self.client = client
        self.model = model

    @handle_async_errors(operation_name="agent LLM call", default_return=None)
    @with_retries(max_retries=2, delay=1.0)
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> Optional[LLMResponse]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # Enable DeepSeek thinking mode
        if "deepseek" in self.model:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        response = await self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message

        # Log thinking content if present (never send to user)
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            logger.debug(f"DeepSeek thinking: {reasoning[:200]}...")

        # Parse tool calls if present
        parsed_tool_calls = None
        if message.tool_calls:
            parsed_tool_calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                parsed_tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=parsed_tool_calls,
            usage=usage,
        )
