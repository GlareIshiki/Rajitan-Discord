"""
Workflow API endpoints for WebUI visualization.

Provides read-only access to workflow configuration
and real-time execution log streaming.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from rajitan.web.auth import get_current_user, verify_discord_token
from rajitan.web.server import app_state
from rajitan.utils.logger import get_logger

logger = get_logger("web.routes.workflow")

router = APIRouter()


def _get_loader():
    return app_state.get("workflow_loader")


def _get_execution_log():
    return app_state.get("execution_log")


# --- Workflow Config Endpoints ---


@router.get("")
async def get_workflow(user=Depends(get_current_user)):
    """基盤ワークフロー（JSON）"""
    loader = _get_loader()
    if not loader:
        return {"error": "Workflow loader not initialized"}

    from dataclasses import asdict
    return asdict(loader.base_config)


@router.get("/yaml")
async def get_workflow_yaml(user=Depends(get_current_user)):
    """基盤ワークフローのYAMLテキスト"""
    loader = _get_loader()
    if not loader:
        return {"error": "Workflow loader not initialized"}

    try:
        with open(loader.path, "r", encoding="utf-8") as f:
            return {"yaml": f.read()}
    except FileNotFoundError:
        return {"error": "Workflow YAML file not found"}


@router.get("/user/{guild_id}/{user_id}")
async def get_user_overlay(guild_id: str, user_id: str, user=Depends(get_current_user)):
    """ユーザーオーバーレイ（YAMLテキスト + パース済みJSON）"""
    loader = _get_loader()
    if not loader:
        return {"error": "Workflow loader not initialized"}

    yaml_text = await loader.get_user_overlay(guild_id, user_id)
    if not yaml_text:
        return {"overlay": None, "yaml": ""}

    import yaml
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        parsed = None

    return {"overlay": parsed, "yaml": yaml_text}


@router.get("/effective/{guild_id}/{user_id}")
async def get_effective_config(guild_id: str, user_id: str, user=Depends(get_current_user)):
    """マージ済み有効ワークフロー"""
    loader = _get_loader()
    if not loader:
        return {"error": "Workflow loader not initialized"}

    from dataclasses import asdict
    config = await loader.get_effective_config(guild_id, user_id)
    return asdict(config)


@router.get("/flow")
async def get_flow_diagram(user=Depends(get_current_user)):
    """フロー図用ノード/エッジデータ"""
    loader = _get_loader()
    if not loader:
        return {"error": "Workflow loader not initialized"}

    wf = loader.base_config
    nodes = [
        {"id": "start", "label": "メッセージ受信", "type": "trigger"},
        {"id": "complexity", "label": f"複雑さ判定\n(min_length={wf.complexity.min_length})", "type": "decision"},
        {"id": "thinking", "label": "Thinking Mode", "type": "process"},
        {"id": "non_thinking", "label": "Non-Thinking Mode", "type": "process"},
        {"id": "agent_loop", "label": f"Agent Loop\n(max_steps={wf.agent_loop.max_steps})", "type": "process"},
        {"id": "tool_call", "label": "Tool Call", "type": "process"},
        {"id": "reflection", "label": f"Reflection\n(every {wf.agent_loop.reflection_interval} steps)", "type": "decision"},
        {"id": "response_gate", "label": "ResponseGate\n(品質チェック)", "type": "decision"},
        {"id": "send", "label": "送信", "type": "output"},
        {"id": "block", "label": "ブロック", "type": "output"},
    ]
    edges = [
        {"from": "start", "to": "complexity"},
        {"from": "complexity", "to": "thinking", "label": "complex"},
        {"from": "complexity", "to": "non_thinking", "label": "simple"},
        {"from": "thinking", "to": "agent_loop"},
        {"from": "non_thinking", "to": "agent_loop"},
        {"from": "agent_loop", "to": "tool_call", "label": "tool_calls"},
        {"from": "tool_call", "to": "agent_loop"},
        {"from": "agent_loop", "to": "reflection", "label": "interval"},
        {"from": "reflection", "to": "agent_loop"},
        {"from": "agent_loop", "to": "response_gate", "label": "final"},
        {"from": "response_gate", "to": "send", "label": "YES"},
        {"from": "response_gate", "to": "block", "label": "NO"},
    ]
    return {"nodes": nodes, "edges": edges}


# --- Execution Log Endpoints ---


@router.get("/executions")
async def get_executions(limit: int = 20, user=Depends(get_current_user)):
    """直近の実行ログ一覧"""
    log = _get_execution_log()
    if not log:
        return {"executions": []}
    return {"executions": log.get_executions(limit)}


@router.get("/events")
async def get_events(limit: int = 50, user=Depends(get_current_user)):
    """直近のイベント一覧"""
    log = _get_execution_log()
    if not log:
        return {"events": []}
    return {"events": log.get_recent(limit)}


# --- WebSocket for real-time streaming ---


@router.websocket("/ws")
async def websocket_execution_stream(websocket: WebSocket, token: str = None):
    """リアルタイム実行ログストリーム（token query paramで認証）"""
    # Authenticate via query parameter
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        await verify_discord_token(token)
    except Exception:
        await websocket.close(code=4003, reason="Invalid token")
        return

    log = _get_execution_log()
    if not log:
        await websocket.close(code=1011, reason="Execution log not initialized")
        return

    await websocket.accept()
    queue = log.subscribe()

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.to_dict())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        log.unsubscribe(queue)
