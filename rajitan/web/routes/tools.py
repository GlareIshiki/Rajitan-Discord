"""Tool catalog API endpoints for WebUI."""

from fastapi import APIRouter, Depends, HTTPException, status
from rajitan.web.auth import get_current_user
from rajitan.web.server import app_state
from rajitan.utils.logger import get_logger

logger = get_logger("web_tools")
router = APIRouter(tags=["tools"])


def _get_tool_registry():
    registry = app_state.get("tool_registry")
    if not registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tool registry not available",
        )
    return registry


@router.get("")
async def list_tools(user=Depends(get_current_user)):
    """全ツール一覧（カテゴリ・メタデータ付き）"""
    registry = _get_tool_registry()
    definitions = registry.list_definitions()

    tools = []
    for td in definitions:
        tools.append({
            "name": td.name,
            "display_name": td.display_name,
            "category": td.category,
            "icon": td.icon,
            "tags": td.tags,
            "description_short": td.ai_description.strip().split("\n")[0] if td.ai_description else "",
            "max_calls_per_execution": td.max_calls_per_execution,
            "handler_type": td.handler_type,
            "requires_context": td.requires_context,
            "parameter_count": len(td.parameters),
        })

    return {
        "tools": sorted(tools, key=lambda t: (t["category"], t["name"])),
        "categories": registry.list_categories(),
        "total": len(tools),
    }


@router.get("/categories")
async def list_categories(user=Depends(get_current_user)):
    """カテゴリ一覧"""
    registry = _get_tool_registry()
    return {"categories": registry.list_categories()}


@router.get("/{tool_name}")
async def get_tool_detail(tool_name: str, user=Depends(get_current_user)):
    """個別ツール詳細（パラメータ定義・実行設定含む）"""
    registry = _get_tool_registry()
    td = registry.get_definition(tool_name)
    if not td:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool not found: {tool_name}",
        )

    return {
        "name": td.name,
        "display_name": td.display_name,
        "category": td.category,
        "icon": td.icon,
        "tags": td.tags,
        "description": td.ai_description,
        "hints": td.hints,
        "parameters": td.parameters,
        "execution": {
            "handler_type": td.handler_type,
            "max_calls_per_execution": td.max_calls_per_execution,
            "requires_context": td.requires_context,
            "service": td.execution_config.get("service", ""),
            "method": td.execution_config.get("method", ""),
            "services": td.execution_config.get("services", []),
        },
        "result_templates": td.result_templates,
        "yaml_path": td.yaml_path,
    }


@router.get("/{tool_name}/yaml")
async def get_tool_yaml(tool_name: str, user=Depends(get_current_user)):
    """ツールのraw YAMLテキスト"""
    registry = _get_tool_registry()
    td = registry.get_definition(tool_name)
    if not td:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool not found: {tool_name}",
        )

    return {
        "name": td.name,
        "yaml": td.raw_yaml,
        "ai_section": td.ai_section_text,
    }
