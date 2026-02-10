from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from halfmaid.bot import voice as voice_module

router = APIRouter()


class PlayRequest(BaseModel):
    guild_id: str
    query: str
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    requester: str = ""


class GuildRequest(BaseModel):
    guild_id: str


class PauseRequest(BaseModel):
    guild_id: str
    action: str = "pause"  # "pause" | "resume"


class VolumeRequest(BaseModel):
    guild_id: str
    volume: int


class LoopRequest(BaseModel):
    guild_id: str
    mode: str  # "off" | "track" | "queue"


class ShuffleRequest(BaseModel):
    guild_id: str


def _get_vm():
    vm = voice_module.voice_manager
    if not vm:
        raise HTTPException(503, detail="音楽ボットが準備中です")
    return vm


@router.post("/play")
async def play(req: PlayRequest):
    vm = _get_vm()
    result = await vm.play(
        guild_id=req.guild_id,
        query=req.query,
        channel_id=req.channel_id,
        user_id=req.user_id,
        requester=req.requester,
    )
    if not result.get("success"):
        raise HTTPException(400, detail=result.get("error", "再生に失敗しました"))
    return result


@router.post("/stop")
async def stop(req: GuildRequest):
    vm = _get_vm()
    return await vm.stop(req.guild_id)


@router.post("/pause")
async def pause(req: PauseRequest):
    vm = _get_vm()
    if req.action == "resume":
        result = await vm.resume(req.guild_id)
    else:
        result = await vm.pause(req.guild_id)
    if not result.get("success"):
        raise HTTPException(400, detail=result.get("error"))
    return result


@router.post("/skip")
async def skip(req: GuildRequest):
    vm = _get_vm()
    result = await vm.skip(req.guild_id)
    if not result.get("success"):
        raise HTTPException(400, detail=result.get("error"))
    return result


@router.post("/volume")
async def volume(req: VolumeRequest):
    vm = _get_vm()
    return await vm.set_volume(req.guild_id, req.volume)


@router.post("/loop")
async def loop(req: LoopRequest):
    vm = _get_vm()
    result = await vm.set_loop(req.guild_id, req.mode)
    if not result.get("success"):
        raise HTTPException(400, detail=result.get("error"))
    return result


@router.post("/shuffle")
async def shuffle(req: ShuffleRequest):
    vm = _get_vm()
    return await vm.toggle_shuffle(req.guild_id)
