"""Tool definition and loader for YAML-driven tool system.

ToolDefinition holds parsed metadata from a tool YAML file.
ToolDefinitionLoader scans the tools/ directory and produces ToolDefinition objects.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.definition")


@dataclass
class ToolDefinition:
    """Parsed from a single tool YAML file."""

    # Identity
    name: str
    yaml_path: str  # relative path from tools/ root

    # Raw YAML text of the ai: section (injected as-is into AI context)
    ai_section_text: str

    # meta: section (for WebUI)
    display_name: str = ""
    category: str = ""
    icon: str = ""
    tags: List[str] = field(default_factory=list)

    # ai: section (parsed for function calling schema generation)
    ai_description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    hints: str = ""

    # execution: section (for GenericExecutor)
    handler_type: str = ""  # service_method | python_class | discord_action | builtin
    max_calls_per_execution: int = 5
    requires_context: bool = False
    execution_config: Dict[str, Any] = field(default_factory=dict)
    result_templates: Dict[str, str] = field(default_factory=dict)

    # Full raw YAML text
    raw_yaml: str = ""

    def get_function_definition(self) -> Dict[str, Any]:
        """Generate OpenAI function calling schema from YAML parameters."""
        properties = {}
        required = []

        for param_name, spec in self.parameters.items():
            prop: Dict[str, Any] = {
                "type": spec.get("type", "string"),
                "description": spec.get("description", ""),
            }
            if "enum" in spec:
                prop["enum"] = spec["enum"]
            if "default" in spec:
                prop["default"] = spec["default"]
            properties[param_name] = prop
            if spec.get("required", False):
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.ai_description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolDefinitionLoader:
    """Loads tool definitions from YAML files in the tools/ directory."""

    def __init__(self, tools_dir: Optional[str] = None):
        if tools_dir is None:
            # Default: <project_root>/tools/
            project_root = Path(__file__).resolve().parents[3]
            self.tools_dir = project_root / "tools"
        else:
            self.tools_dir = Path(tools_dir)

    def load_all(self) -> Dict[str, ToolDefinition]:
        """Scan tools/ directory and load all YAML tool definitions."""
        definitions: Dict[str, ToolDefinition] = {}

        if not self.tools_dir.exists():
            logger.warning(f"Tools directory not found: {self.tools_dir}")
            return definitions

        for yaml_path in sorted(self.tools_dir.rglob("*.yaml")):
            try:
                tool_def = self._load_file(yaml_path)
                if tool_def:
                    if tool_def.name in definitions:
                        logger.warning(
                            f"Duplicate tool name '{tool_def.name}' in {yaml_path}, "
                            f"overwriting previous from {definitions[tool_def.name].yaml_path}"
                        )
                    definitions[tool_def.name] = tool_def
                    logger.info(f"Loaded tool definition: {tool_def.name} ({yaml_path.name})")
            except Exception as e:
                logger.error(f"Failed to load tool YAML {yaml_path}: {e}")

        logger.info(f"Loaded {len(definitions)} tool definitions from {self.tools_dir}")
        return definitions

    def _load_file(self, yaml_path: Path) -> Optional[ToolDefinition]:
        """Parse a single YAML file into a ToolDefinition."""
        raw_yaml = yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_yaml)

        if not data or not isinstance(data, dict):
            logger.warning(f"Empty or invalid YAML: {yaml_path}")
            return None

        ai = data.get("ai", {})
        meta = data.get("meta", {})
        execution = data.get("execution", {})

        name = ai.get("name", "")
        if not name:
            logger.warning(f"Tool YAML missing ai.name: {yaml_path}")
            return None

        # Extract the ai: section as raw text for AI context injection
        ai_section_text = self._extract_ai_section_text(raw_yaml)

        # Relative path from tools/ root
        try:
            rel_path = str(yaml_path.relative_to(self.tools_dir))
        except ValueError:
            rel_path = str(yaml_path)

        return ToolDefinition(
            name=name,
            yaml_path=rel_path,
            raw_yaml=raw_yaml,
            ai_section_text=ai_section_text,
            # meta
            display_name=meta.get("display_name", name),
            category=meta.get("category", self._infer_category(yaml_path)),
            icon=meta.get("icon", ""),
            tags=meta.get("tags", []),
            # ai
            ai_description=ai.get("description", ""),
            parameters=ai.get("parameters", {}),
            hints=ai.get("hints", ""),
            # execution
            handler_type=execution.get("handler", ""),
            max_calls_per_execution=execution.get("max_calls_per_execution", 5),
            requires_context=execution.get("requires_context", False),
            execution_config=execution,
            result_templates=execution.get("result", {}),
        )

    def _extract_ai_section_text(self, raw_yaml: str) -> str:
        """Extract the ai: section as raw text.

        Finds the 'ai:' top-level key and captures everything until the next
        top-level key (a line starting with a non-space, non-comment character).
        """
        lines = raw_yaml.split("\n")
        in_ai = False
        ai_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped == "ai:" or stripped.startswith("ai:"):
                in_ai = True
                ai_lines.append(line)
                continue

            if in_ai:
                # A new top-level key starts (non-indented, non-empty, non-comment)
                if line and not line[0].isspace() and not line.startswith("#"):
                    break
                ai_lines.append(line)

        return "\n".join(ai_lines).rstrip()

    def _infer_category(self, yaml_path: Path) -> str:
        """Infer category from directory name."""
        parent = yaml_path.parent.name
        if parent == "tools":
            return "uncategorized"
        return parent
