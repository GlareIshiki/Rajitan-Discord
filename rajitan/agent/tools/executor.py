"""Generic tool executor for YAML-driven tool system.

Replaces individual Tool classes with a unified execution layer.
Three handler types route tool calls to the appropriate execution logic.
"""

import importlib
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from rajitan.agent.tools.base import ToolResult
from rajitan.agent.tools.definition import ToolDefinition
from rajitan.agent.tools.service_registry import ServiceRegistry
from rajitan.utils.config import get_config
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.executor")

_WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


class GenericExecutor:
    """Unified execution layer for YAML-defined tools."""

    def __init__(self, service_registry: ServiceRegistry):
        self.services = service_registry
        self._builtin_handlers: Dict[str, Any] = {
            "get_current_time": self._builtin_get_current_time,
            "web_search": self._builtin_web_search,
            "music_player_api": self._builtin_music_player_api,
        }

    async def execute(
        self,
        tool_def: ToolDefinition,
        params: Dict[str, Any],
        agent_context: Optional[Any] = None,
    ) -> ToolResult:
        """Execute a YAML-defined tool."""
        handler_type = tool_def.handler_type

        if handler_type == "builtin":
            return await self._handle_builtin(tool_def, params, agent_context)
        elif handler_type == "discord_action":
            return await self._handle_discord_action(tool_def, params, agent_context)
        elif handler_type == "service_method":
            return await self._handle_service_method(tool_def, params, agent_context)
        elif handler_type == "python_class":
            return await self._handle_python_class(tool_def, params, agent_context)
        else:
            return ToolResult(success=False, error=f"Unknown handler type: {handler_type}")

    # --- Builtin handler ---

    async def _handle_builtin(
        self,
        tool_def: ToolDefinition,
        params: Dict[str, Any],
        agent_context: Optional[Any],
    ) -> ToolResult:
        """Handle tools with simple builtin logic."""
        builtin_name = tool_def.execution_config.get("builtin", "")
        handler = self._builtin_handlers.get(builtin_name)
        if not handler:
            return ToolResult(success=False, error=f"Unknown builtin: {builtin_name}")
        return await handler(params, agent_context, tool_def=tool_def)

    async def _builtin_get_current_time(
        self, params: Dict[str, Any], agent_context: Optional[Any], **kwargs
    ) -> ToolResult:
        now = datetime.now()
        formatted = (
            f"{now.strftime('%Y年%m月%d日')}"
            f"（{_WEEKDAYS[now.weekday()]}曜日）"
            f"{now.strftime('%H時%M分')}"
        )
        return ToolResult(success=True, data=formatted)

    async def _builtin_web_search(
        self, params: Dict[str, Any], agent_context: Optional[Any], **kwargs
    ) -> ToolResult:
        config = get_config()
        api_key = config.brave_search_api_key

        if not api_key:
            return ToolResult(success=False, error="Brave Search APIキーが設定されていない")

        query = params.get("query", "")
        if not query:
            return ToolResult(success=False, error="検索クエリが空です")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "X-Subscription-Token": api_key,
                        "Accept": "application/json",
                    },
                    params={"q": query, "count": 5},
                )
                response.raise_for_status()
                web_results = response.json().get("web", {}).get("results", [])

            results = []
            for item in web_results[:5]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })

            if not results:
                return ToolResult(success=True, data="検索結果が見つかりませんでした。")

            return ToolResult(success=True, data=results)

        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            logger.error(f"Brave Search API error: {e.response.status_code} — {body}")
            return ToolResult(success=False, error=f"検索APIエラー: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(success=False, error=f"検索に失敗: {e}")

    async def _builtin_music_player_api(
        self, params: Dict[str, Any], agent_context: Optional[Any], **kwargs
    ) -> ToolResult:
        """Forward music player commands to the music bot REST API."""
        config = get_config()
        base_url = config.halfmaid_api_url

        tool_def = kwargs.get("tool_def")
        exec_config = tool_def.execution_config if tool_def else {}
        endpoint = exec_config.get("_endpoint", "")
        method = exec_config.get("_method", "POST")

        if not endpoint:
            return ToolResult(success=False, error="Missing _endpoint in tool config")

        # Auto-inject context
        if agent_context:
            params.setdefault("guild_id", agent_context.guild_id)
            params.setdefault("user_id", agent_context.user_id)
            params.setdefault("requester", agent_context.username)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if method == "GET":
                    url = f"{base_url}{endpoint}"
                    # For GET with path params like /status/{guild_id}
                    if "{guild_id}" in endpoint:
                        url = f"{base_url}{endpoint.replace('{guild_id}', params.pop('guild_id', ''))}"
                    resp = await client.get(url, params=params)
                else:
                    resp = await client.post(f"{base_url}{endpoint}", json=params)

                if resp.status_code >= 400:
                    try:
                        error_data = resp.json()
                        error_msg = error_data.get("detail", str(resp.status_code))
                    except Exception:
                        error_msg = f"HTTP {resp.status_code}"
                    logger.warning(f"Music API {method} {endpoint}: {resp.status_code} — {error_msg}")
                    return ToolResult(success=False, error=error_msg)

                return ToolResult(success=True, data=resp.json())

        except httpx.ConnectError:
            return ToolResult(
                success=False, error="音楽ボットに接続できません（オフライン）"
            )
        except httpx.TimeoutException:
            return ToolResult(
                success=False, error="音楽ボットの応答がタイムアウトしました（60秒）"
            )
        except Exception as e:
            logger.error(f"Music player API call failed: {type(e).__name__}: {e}")
            return ToolResult(success=False, error=f"音楽ボットAPI呼び出しに失敗: {e}")

    # --- Discord action handler ---

    async def _handle_discord_action(
        self,
        tool_def: ToolDefinition,
        params: Dict[str, Any],
        agent_context: Optional[Any],
    ) -> ToolResult:
        """Handle Discord API actions (send_message, add_reaction)."""
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        action = tool_def.execution_config.get("action", "")

        try:
            if action == "send_message":
                content = params.get("content", "")
                if not content:
                    return ToolResult(success=False, error="送信するメッセージが空。")
                await agent_context.message.channel.send(content)
                return ToolResult(success=True, data="メッセージを送信した。")

            elif action == "add_reaction":
                emoji = params.get("emoji", "👍")
                await agent_context.message.add_reaction(emoji)
                return ToolResult(success=True, data=f"リアクション {emoji} を追加した。")

            else:
                return ToolResult(success=False, error=f"Unknown discord action: {action}")

        except Exception as e:
            return ToolResult(success=False, error=f"Discord操作に失敗: {e}")

    # --- Service method handler ---

    async def _handle_service_method(
        self,
        tool_def: ToolDefinition,
        params: Dict[str, Any],
        agent_context: Optional[Any],
    ) -> ToolResult:
        """Handle tools that delegate to a service method."""
        exec_config = tool_def.execution_config
        service_name = exec_config.get("service", "")
        method_name = exec_config.get("method", "")

        service = self.services.get(service_name)
        if service is None:
            return ToolResult(success=False, error=f"Service not found: {service_name}")

        method = getattr(service, method_name, None)
        if method is None:
            return ToolResult(
                success=False,
                error=f"Method '{method_name}' not found on service '{service_name}'",
            )

        # Resolve arguments from arg_mapping
        arg_mapping = exec_config.get("arg_mapping", {})
        try:
            resolved_args = self._resolve_args(arg_mapping, params, agent_context)
        except Exception as e:
            return ToolResult(success=False, error=f"Argument resolution failed: {e}")

        # Handle _construct pattern (build a dataclass/model)
        construct_class = arg_mapping.get("_construct")
        try:
            if construct_class:
                cls = self._import_class(construct_class)
                fields = resolved_args.get("_fields", resolved_args)
                arg_obj = cls(**fields)
                result = await method(arg_obj)
            else:
                result = await method(**resolved_args)
        except Exception as e:
            logger.error(f"Service method execution failed: {e}")
            templates = tool_def.result_templates
            if templates.get("on_failure"):
                return ToolResult(success=False, error=templates["on_failure"])
            return ToolResult(success=False, error=str(e))

        # Format result
        templates = tool_def.result_templates
        if templates.get("on_success") and result is not None:
            try:
                msg = templates["on_success"].format(params=type("P", (), params)())
                return ToolResult(success=True, data=msg)
            except Exception:
                pass

        if result is not None:
            return ToolResult(success=True, data=result)
        return ToolResult(success=True, data="完了")

    def _resolve_args(
        self,
        arg_mapping: Dict[str, Any],
        params: Dict[str, Any],
        agent_context: Optional[Any],
    ) -> Dict[str, Any]:
        """Resolve $context.* and $params.* references in arg_mapping."""
        if not arg_mapping:
            return params

        # If _construct pattern, resolve _fields
        if "_construct" in arg_mapping:
            fields = arg_mapping.get("_fields", {})
            resolved_fields = {}
            for key, value in fields.items():
                resolved_fields[key] = self._resolve_value(value, params, agent_context)
            return {"_fields": resolved_fields}

        # Direct mapping
        resolved = {}
        for key, value in arg_mapping.items():
            if key.startswith("_"):
                continue
            resolved[key] = self._resolve_value(value, params, agent_context)
        return resolved

    def _resolve_value(
        self, value: Any, params: Dict[str, Any], agent_context: Optional[Any]
    ) -> Any:
        """Resolve a single value reference."""
        if not isinstance(value, str):
            return value

        if value.startswith("$context."):
            attr = value[len("$context."):]
            if agent_context is None:
                return None
            return getattr(agent_context, attr, None)

        if value.startswith("$params."):
            param_name = value[len("$params."):]
            return params.get(param_name)

        return value

    # --- Python class handler ---

    async def _handle_python_class(
        self,
        tool_def: ToolDefinition,
        params: Dict[str, Any],
        agent_context: Optional[Any],
    ) -> ToolResult:
        """Handle complex tools with custom Python handler classes."""
        exec_config = tool_def.execution_config
        module_path = exec_config.get("module", "")
        class_name = exec_config.get("class", "")

        if not module_path or not class_name:
            return ToolResult(
                success=False, error="python_class handler requires 'module' and 'class'"
            )

        try:
            cls = self._import_class(f"{module_path}.{class_name}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to import handler: {e}")

        # Inject required services (positional, matching original constructor patterns)
        service_names = exec_config.get("services", [])
        service_instances = []
        for svc_name in service_names:
            svc = self.services.get(svc_name)
            if svc is None:
                return ToolResult(success=False, error=f"Required service not found: {svc_name}")
            service_instances.append(svc)

        try:
            handler = cls(*service_instances)
            # Spread params as kwargs for compatibility with existing Tool classes
            return await handler.execute(agent_context=agent_context, **params)
        except Exception as e:
            logger.error(f"Python class handler execution failed: {e}")
            return ToolResult(success=False, error=str(e))

    # --- Utilities ---

    @staticmethod
    def _import_class(full_class_path: str) -> type:
        """Dynamically import a class from 'module.path.ClassName'."""
        parts = full_class_path.rsplit(".", 1)
        if len(parts) != 2:
            raise ImportError(f"Invalid class path: {full_class_path}")
        module_path, class_name = parts
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
