import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.tools.definition import ToolDefinition
    from rajitan.agent.tools.executor import GenericExecutor
    from rajitan.agent.workflow.schema import ToolsConfig

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
    max_calls_per_execution: int = 5  # Per-execution call limit (override in subclass)

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
    """Central registry for all available tools.

    Supports dual mode:
    - Legacy Tool class instances (execute via tool.execute())
    - YAML ToolDefinition objects (execute via GenericExecutor)
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._yaml_tools: Dict[str, "ToolDefinition"] = {}
        self._executor: Optional["GenericExecutor"] = None
        self._call_counts: Dict[str, int] = {}

    def set_executor(self, executor: "GenericExecutor") -> None:
        """Set the GenericExecutor for YAML-defined tools."""
        self._executor = executor

    def reset_call_counts(self):
        """Reset per-execution call counts (called at start of each execute)"""
        self._call_counts = {}

    def register(self, tool: Tool) -> None:
        """Register a legacy Tool class instance."""
        if not tool.name:
            raise ValueError("Tool must have a name")
        if tool.name in self._tools or tool.name in self._yaml_tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def register_yaml(self, tool_def: "ToolDefinition") -> None:
        """Register a YAML-defined tool."""
        if not tool_def.name:
            raise ValueError("ToolDefinition must have a name")
        if tool_def.name in self._tools:
            # Remove legacy version when YAML version replaces it
            del self._tools[tool_def.name]
            logger.info(f"Replaced legacy tool with YAML: {tool_def.name}")
        if tool_def.name in self._yaml_tools:
            logger.warning(f"YAML tool '{tool_def.name}' already registered, overwriting")
        self._yaml_tools[tool_def.name] = tool_def
        logger.info(f"Registered YAML tool: {tool_def.name}")

    def get(self, name: str) -> Optional[Tool]:
        """Get a legacy Tool instance by name (returns None for YAML tools)."""
        return self._tools.get(name)

    def get_definition(self, name: str) -> Optional["ToolDefinition"]:
        """Get a YAML ToolDefinition by name."""
        return self._yaml_tools.get(name)

    def _get_max_calls(self, name: str) -> int:
        """Get max_calls_per_execution for a tool (legacy or YAML)."""
        if name in self._tools:
            return self._tools[name].max_calls_per_execution
        if name in self._yaml_tools:
            return self._yaml_tools[name].max_calls_per_execution
        return 5

    async def execute(self, name: str, disabled: set = None, **kwargs) -> ToolResult:
        """Execute a tool by name, enforcing per-execution call limits.

        Handles both legacy Tool instances and YAML ToolDefinitions.
        """
        if disabled and name in disabled:
            return ToolResult(success=False, error=f"Tool '{name}' is disabled.")

        # Check call limits
        max_calls = self._get_max_calls(name)
        count = self._call_counts.get(name, 0)
        if count >= max_calls:
            return ToolResult(
                success=False,
                error=f"このツールは1回の実行で{max_calls}回まで使用可能。上限に達した。",
            )

        try:
            # YAML tool path
            if name in self._yaml_tools:
                if self._executor is None:
                    return ToolResult(
                        success=False, error="GenericExecutor not configured"
                    )
                tool_def = self._yaml_tools[name]
                # Separate agent_context from tool params
                agent_context = kwargs.pop("agent_context", None)
                result = await self._executor.execute(tool_def, kwargs, agent_context)

            # Legacy tool path
            elif name in self._tools:
                result = await self._tools[name].execute(**kwargs)

            else:
                return ToolResult(success=False, error=f"Unknown tool: {name}")

            self._call_counts[name] = count + 1
            return result

        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            return ToolResult(success=False, error=str(e))

    def get_function_definitions(self, exclude: set = None) -> List[Dict[str, Any]]:
        """Get tool definitions for OpenAI function calling, optionally excluding some."""
        defs = []
        for tool in self._tools.values():
            if exclude and tool.name in exclude:
                continue
            defs.append(tool.get_function_definition())
        for tool_def in self._yaml_tools.values():
            if exclude and tool_def.name in exclude:
                continue
            defs.append(tool_def.get_function_definition())
        return defs

    def apply_workflow_config(self, tools_config: "ToolsConfig") -> None:
        """Apply base workflow tool configuration at startup (non-destructive)."""
        # Apply default max_calls to all tools
        for tool in self._tools.values():
            tool.max_calls_per_execution = tools_config.default_max_calls
        for tool_def in self._yaml_tools.values():
            tool_def.max_calls_per_execution = tools_config.default_max_calls

        # Apply per-tool overrides
        for name, override in tools_config.overrides.items():
            tool = self._tools.get(name)
            if tool:
                tool.max_calls_per_execution = override.max_calls_per_execution
                logger.info(f"Tool '{name}' max_calls set to {override.max_calls_per_execution}")
            tool_def = self._yaml_tools.get(name)
            if tool_def:
                tool_def.max_calls_per_execution = override.max_calls_per_execution
                logger.info(f"YAML tool '{name}' max_calls set to {override.max_calls_per_execution}")

    def apply_per_execution_config(self, tools_config: "ToolsConfig") -> set:
        """Apply per-execution tool config. Returns set of disabled tool names.

        Updates max_calls on tool instances and returns disabled set for filtering.
        Call reset_call_counts() before this method.
        """
        # Apply default max_calls
        for tool in self._tools.values():
            tool.max_calls_per_execution = tools_config.default_max_calls
        for tool_def in self._yaml_tools.values():
            tool_def.max_calls_per_execution = tools_config.default_max_calls

        # Apply per-tool overrides
        for name, override in tools_config.overrides.items():
            tool = self._tools.get(name)
            if tool:
                tool.max_calls_per_execution = override.max_calls_per_execution
            tool_def = self._yaml_tools.get(name)
            if tool_def:
                tool_def.max_calls_per_execution = override.max_calls_per_execution

        return set(tools_config.disabled)

    def list_tools(self) -> List[str]:
        """List all registered tool names (legacy + YAML)."""
        return list(self._tools.keys()) + list(self._yaml_tools.keys())

    def list_definitions(self) -> List["ToolDefinition"]:
        """List all YAML tool definitions (for WebUI API)."""
        return list(self._yaml_tools.values())

    def list_categories(self) -> List[Dict[str, Any]]:
        """List unique categories from YAML tool definitions."""
        categories: Dict[str, int] = {}
        for td in self._yaml_tools.values():
            cat = td.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1
        return [{"name": k, "tool_count": v} for k, v in sorted(categories.items())]

    def __len__(self) -> int:
        return len(self._tools) + len(self._yaml_tools)
