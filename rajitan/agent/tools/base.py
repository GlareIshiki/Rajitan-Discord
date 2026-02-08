import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools")


@dataclass
class ToolResult:
    """Standardized result from tool execution"""
    success: bool
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"success": self.success}
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        return result

    def to_content_string(self) -> str:
        """Format for LLM context (appended as tool result)"""
        if self.success:
            if isinstance(self.data, str):
                return self.data
            return json.dumps(self.data, ensure_ascii=False, default=str)
        return f"Error: {self.error}"


class Tool(ABC):
    """Abstract base class for agent tools"""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments"""
        pass

    def get_function_definition(self) -> Dict[str, Any]:
        """Generate OpenAI function calling schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Central registry for all available tools"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    async def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name"""
        tool = self.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            return ToolResult(success=False, error=str(e))

    def get_function_definitions(self) -> List[Dict[str, Any]]:
        """Get all tool definitions for OpenAI function calling"""
        return [tool.get_function_definition() for tool in self._tools.values()]

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)
