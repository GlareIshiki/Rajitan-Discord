"""
WorkflowLoader — YAML-based workflow configuration loader.

Loads the base workflow from workflows/default.yaml and merges
per-user overlays stored in SQLite. Falls back to dataclass defaults
if the YAML file is missing or invalid.
"""

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from rajitan.agent.workflow.schema import (
    AgentLoopConfig,
    ComplexityConfig,
    ContextConfig,
    PromptsConfig,
    ResponseGateConfig,
    StepInjectionConfig,
    StepParams,
    TeamConfig,
    ToolOverride,
    ToolsConfig,
    WorkflowConfig,
)
from rajitan.utils.logger import get_logger

logger = get_logger("agent.workflow.loader")

DEFAULT_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / "workflows" / "default.yaml"

# Fields users are allowed to override via chat
_USER_OVERLAY_ALLOWED = {"prompts", "tools"}


class WorkflowLoader:
    """Loads and merges base workflow + per-user overlays."""

    def __init__(self, path: Optional[Path] = None, db_client=None):
        self.path = path or DEFAULT_WORKFLOW_PATH
        self._db = db_client
        self._base_config: Optional[WorkflowConfig] = None
        self._raw: Optional[dict] = None
        self._load_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Base workflow
    # ------------------------------------------------------------------

    @property
    def base_config(self) -> WorkflowConfig:
        if self._base_config is None:
            self.load()
        return self._base_config

    @property
    def raw_yaml(self) -> Optional[dict]:
        return self._raw

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def load(self) -> WorkflowConfig:
        """Load base workflow from YAML. Falls back to defaults on error."""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._raw = yaml.safe_load(f)
            self._base_config = self._parse(self._raw)
            self._load_error = None
            logger.info(f"Workflow loaded: {self.path} (name={self._base_config.name})")
        except FileNotFoundError:
            logger.warning(f"Workflow file not found: {self.path}, using defaults")
            self._base_config = WorkflowConfig()
            self._load_error = "file_not_found"
        except Exception as e:
            logger.error(f"Failed to load workflow: {e}, using defaults")
            self._base_config = WorkflowConfig()
            self._load_error = str(e)
        return self._base_config

    def reload(self) -> WorkflowConfig:
        """Reload base workflow from disk."""
        return self.load()

    def validate(self) -> List[str]:
        """Minimal validation. Returns list of error strings (empty = valid)."""
        errors: List[str] = []
        if self._raw is None:
            errors.append("No YAML data loaded")
            return errors

        for key in ("version", "agent_loop", "prompts", "tools"):
            if key not in self._raw:
                errors.append(f"Missing required key: {key}")

        al = self._raw.get("agent_loop", {})
        if "max_steps" in al:
            if not isinstance(al["max_steps"], int):
                errors.append("agent_loop.max_steps must be integer")
            elif al["max_steps"] < 1:
                errors.append("agent_loop.max_steps must be >= 1")

        if "temperature" in al:
            if not isinstance(al["temperature"], (int, float)):
                errors.append("agent_loop.temperature must be a number")

        return errors

    # ------------------------------------------------------------------
    # Per-user overlay (SQLite)
    # ------------------------------------------------------------------

    async def get_effective_config(
        self, guild_id: str, user_id: str
    ) -> WorkflowConfig:
        """Merge base config + user overlay for this guild/user."""
        base = self.base_config
        overlay_yaml = await self.get_user_overlay(guild_id, user_id)
        if not overlay_yaml:
            return base

        try:
            overlay_dict = yaml.safe_load(overlay_yaml)
            if not isinstance(overlay_dict, dict):
                return base
            return self._merge_overlay(base, overlay_dict)
        except Exception as e:
            logger.warning(f"Failed to parse user overlay for {guild_id}/{user_id}: {e}")
            return base

    async def get_user_overlay(
        self, guild_id: str, user_id: str
    ) -> Optional[str]:
        """Get raw YAML text of user overlay from SQLite."""
        if not self._db:
            return None
        try:
            return await self._db.get_user_workflow(guild_id, user_id)
        except Exception as e:
            logger.warning(f"Failed to get user workflow: {e}")
            return None

    async def save_user_overlay(
        self, guild_id: str, user_id: str, overlay_yaml: str
    ) -> bool:
        """Save user overlay YAML to SQLite. Returns True on success."""
        if not self._db:
            logger.warning("No DB client, cannot save user overlay")
            return False
        await self._db.save_user_workflow(guild_id, user_id, overlay_yaml)
        return True

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, raw: dict) -> WorkflowConfig:
        """Parse raw YAML dict into WorkflowConfig."""
        return WorkflowConfig(
            version=raw.get("version", 1),
            name=raw.get("name", "default"),
            description=raw.get("description", ""),
            agent_loop=self._parse_agent_loop(raw.get("agent_loop", {})),
            complexity=self._parse_complexity(raw.get("complexity", {})),
            context=self._parse_context(raw.get("context", {})),
            response_gate=self._parse_response_gate(raw.get("response_gate", {})),
            prompts=self._parse_prompts(raw.get("prompts", {})),
            tools=self._parse_tools(raw.get("tools", {})),
            team=self._parse_team(raw.get("team", {})),
        )

    def _parse_agent_loop(self, d: dict) -> AgentLoopConfig:
        sp = d.get("step_params", {})
        return AgentLoopConfig(
            max_steps=d.get("max_steps", 15),
            temperature=d.get("temperature", 0.7),
            step_params_normal=self._parse_step_params(sp.get("normal", {}), 1500, True),
            step_params_near_end=self._parse_step_params(sp.get("near_end", {}), 800, True),
            step_params_final=self._parse_step_params(sp.get("final", {}), 800, False),
            reflection_interval=d.get("reflection_interval", 3),
            urgency_threshold=d.get("urgency_threshold", 3),
        )

    def _parse_step_params(self, d: dict, default_tokens: int, default_tools: bool) -> StepParams:
        return StepParams(
            max_tokens=d.get("max_tokens", default_tokens),
            tools_enabled=d.get("tools_enabled", default_tools),
        )

    def _parse_complexity(self, d: dict) -> ComplexityConfig:
        cfg = ComplexityConfig()
        cfg.min_length = d.get("min_length", cfg.min_length)
        if "light_patterns" in d and isinstance(d["light_patterns"], list):
            cfg.light_patterns = d["light_patterns"]
        return cfg

    def _parse_context(self, d: dict) -> ContextConfig:
        return ContextConfig(
            warning_threshold=d.get("warning_threshold", 80_000),
            keep_last_n_exchanges=d.get("keep_last_n_exchanges", 4),
            chars_per_token=d.get("chars_per_token", 3),
            summary_keep_entries=d.get("summary_keep_entries", 6),
        )

    def _parse_response_gate(self, d: dict) -> ResponseGateConfig:
        return ResponseGateConfig(
            timeout_seconds=d.get("timeout_seconds", 10.0),
            max_tokens=d.get("max_tokens", 5),
            temperature=d.get("temperature", 0.0),
            thinking=d.get("thinking", False),
            failsafe_send=d.get("failsafe_send", True),
            failsafe_participate=d.get("failsafe_participate", "skip"),
            gate_prompt=d.get("gate_prompt", ""),
            participate_prompt=d.get("participate_prompt", ""),
        )

    def _parse_prompts(self, d: dict) -> PromptsConfig:
        si_raw = d.get("step_injection", {})
        step_injection = StepInjectionConfig(
            first_step=si_raw.get("first_step", StepInjectionConfig.first_step),
            normal=si_raw.get("normal", StepInjectionConfig.normal),
            reflection=si_raw.get("reflection", StepInjectionConfig.reflection),
            urgency=si_raw.get("urgency", StepInjectionConfig.urgency),
            final_step=si_raw.get("final_step", StepInjectionConfig.final_step),
        )

        defaults = PromptsConfig()
        return PromptsConfig(
            identity=d.get("identity", defaults.identity),
            thinking_protocol=d.get("thinking_protocol", defaults.thinking_protocol),
            tool_usage_guide=d.get("tool_usage_guide", defaults.tool_usage_guide),
            error_recovery_guide=d.get("error_recovery_guide", defaults.error_recovery_guide),
            response_format_guide=d.get("response_format_guide", defaults.response_format_guide),
            memory_usage_guide=d.get("memory_usage_guide", defaults.memory_usage_guide),
            step_injection=step_injection,
            messages={**defaults.messages, **d.get("messages", {})},
        )

    def _parse_tools(self, d: dict) -> ToolsConfig:
        overrides = {}
        for name, override_dict in d.get("overrides", {}).items():
            if isinstance(override_dict, dict):
                overrides[name] = ToolOverride(
                    max_calls_per_execution=override_dict.get("max_calls_per_execution", 5)
                )
        return ToolsConfig(
            default_max_calls=d.get("defaults", {}).get("max_calls_per_execution", 5),
            overrides=overrides,
            disabled=d.get("disabled", []),
        )

    def _parse_team(self, d: dict) -> TeamConfig:
        return TeamConfig(
            enabled=d.get("enabled", False),
            max_sub_agents=d.get("max_sub_agents", 3),
            sub_agent_max_steps=d.get("sub_agent_max_steps", 8),
            sub_agent_timeout_seconds=d.get("sub_agent_timeout_seconds", 60.0),
            sub_agent_temperature=d.get("sub_agent_temperature", 0.7),
            sub_agent_max_tokens=d.get("sub_agent_max_tokens", 1500),
            decompose_max_tokens=d.get("decompose_max_tokens", 800),
            decompose_temperature=d.get("decompose_temperature", 0.3),
            synthesize_max_tokens=d.get("synthesize_max_tokens", 1500),
            synthesize_temperature=d.get("synthesize_temperature", 0.7),
            min_message_length=d.get("min_message_length", 30),
        )

    # ------------------------------------------------------------------
    # Overlay merging
    # ------------------------------------------------------------------

    def _merge_overlay(self, base: WorkflowConfig, overlay: dict) -> WorkflowConfig:
        """Deep-merge user overlay into a copy of base config.

        Only sections in _USER_OVERLAY_ALLOWED are merged.
        Other sections are ignored even if present in the overlay.
        """
        merged = copy.deepcopy(base)

        for key in _USER_OVERLAY_ALLOWED:
            if key not in overlay or not isinstance(overlay[key], dict):
                continue
            if key == "prompts":
                self._merge_prompts(merged.prompts, overlay[key])
            elif key == "tools":
                self._merge_tools(merged.tools, overlay[key])

        return merged

    def _merge_prompts(self, target: PromptsConfig, overlay: dict):
        """Merge overlay prompts into target (in-place)."""
        for key in ("identity", "thinking_protocol", "tool_usage_guide",
                     "error_recovery_guide", "response_format_guide",
                     "memory_usage_guide"):
            if key in overlay and isinstance(overlay[key], str):
                setattr(target, key, overlay[key])

        if "step_injection" in overlay and isinstance(overlay["step_injection"], dict):
            si = overlay["step_injection"]
            for key in ("first_step", "normal", "reflection", "urgency", "final_step"):
                if key in si and isinstance(si[key], str):
                    setattr(target.step_injection, key, si[key])

        if "messages" in overlay and isinstance(overlay["messages"], dict):
            for key, val in overlay["messages"].items():
                if isinstance(val, str):
                    target.messages[key] = val

    _MAX_CALLS_LIMIT = 20  # Upper bound for per-execution tool call limit

    def _merge_tools(self, target: ToolsConfig, overlay: dict):
        """Merge overlay tool config into target (in-place) with validation."""
        if "disabled" in overlay and isinstance(overlay["disabled"], list):
            # Only accept string tool names
            target.disabled = [d for d in overlay["disabled"] if isinstance(d, str)]

        if "overrides" in overlay and isinstance(overlay["overrides"], dict):
            for name, override_dict in overlay["overrides"].items():
                if isinstance(override_dict, dict) and "max_calls_per_execution" in override_dict:
                    val = override_dict["max_calls_per_execution"]
                    if isinstance(val, int):
                        target.overrides[name] = ToolOverride(
                            max_calls_per_execution=max(1, min(self._MAX_CALLS_LIMIT, val))
                        )

        if "defaults" in overlay and isinstance(overlay["defaults"], dict):
            val = overlay["defaults"].get("max_calls_per_execution")
            if isinstance(val, int):
                target.default_max_calls = max(1, min(self._MAX_CALLS_LIMIT, val))
