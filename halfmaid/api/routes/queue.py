from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from halfmaid.bot import voice as voice_module

router = APIRouter()


class QueueActionRequest(BaseModel):
    guild_id: str
    action: str = "view"  # "view" | "clear" | "remove"
    index: Optional[int] = None


def _get_vm():
    vm = voice_module.voice_manager
    if not vm:
        raise HTTPException(503, detail="音楽ボットが準備中です")
    return vm


@router.post("")
async def queue_action(req: QueueActionRequest):
    """Unified queue action endpoint for Rajitan tool integration."""
    vm = _get_vm()
    if req.action == "clear":
        count = vm.queue.get(req.guild_id).clear()
        return {"success": True, "removed": count}
    elif req.action == "remove":
        if req.index is None:
            raise HTTPException(400, detail="index が必要です")
        removed = vm.queue.get(req.guild_id).remove(req.index)
        if not removed:
            raise HTTPException(404, detail=f"キュー位置 {req.index} に曲がありません")
        return {"success": True, "removed": vm._track_dict(removed)}
    else:
        # view
        state = vm._state(req.guild_id)
        info = vm.queue.get_queue_info(req.guild_id)
        current = None
        if state.current_track:
            current = vm._track_dict(state.current_track)
        return {"current_track": current, **info}


@router.get("/{guild_id}")
async def get_queue(guild_id: str):
    vm = _get_vm()
    state = vm._state(guild_id)
    info = vm.queue.get_queue_info(guild_id)

    current = None
    if state.current_track:
        current = vm._track_dict(state.current_track)

    return {"current_track": current, **info}


@router.delete("/{guild_id}")
async def clear_queue(guild_id: str):
    vm = _get_vm()
    count = vm.queue.get(guild_id).clear()
    return {"success": True, "removed": count}


@router.delete("/{guild_id}/{index}")
async def remove_from_queue(guild_id: str, index: int):
    vm = _get_vm()
    removed = vm.queue.get(guild_id).remove(index)
    if not removed:
        raise HTTPException(404, detail=f"キュー位置 {index} に曲がありません")
    return {"success": True, "removed": vm._track_dict(removed)}
