from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from halfmaid.bot import voice as voice_module
from halfmaid.storage.database import PlaylistDatabase
from halfmaid.utils.logger import get_logger

logger = get_logger("api.playlist")
router = APIRouter()
db = PlaylistDatabase()


class PlaylistActionRequest(BaseModel):
    guild_id: str
    action: str  # "list" | "save" | "load" | "delete"
    name: Optional[str] = None
    playlist_id: Optional[int] = None
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    requester: Optional[str] = None


class SavePlaylistRequest(BaseModel):
    guild_id: str
    name: str
    created_by: str = ""


class LoadPlaylistRequest(BaseModel):
    guild_id: str
    playlist_id: int
    channel_id: Optional[str] = None
    user_id: Optional[str] = None


@router.post("/action")
async def playlist_action(req: PlaylistActionRequest):
    """Unified playlist action endpoint for Rajitan tool integration."""
    if req.action == "list":
        playlists = await db.list_playlists(req.guild_id)
        return {"playlists": playlists}

    elif req.action == "save":
        if not req.name:
            raise HTTPException(400, detail="プレイリスト名が必要です")
        vm = voice_module.voice_manager
        if not vm:
            raise HTTPException(503, detail="音楽ボットが準備中です")

        state = vm._state(req.guild_id)
        gq = vm.queue.get(req.guild_id)
        tracks = []
        if state.current_track:
            t = state.current_track
            tracks.append({"title": t.title, "artist": t.artist, "url": t.url, "duration_seconds": t.duration_seconds})
        for t in gq.tracks:
            tracks.append({"title": t.title, "artist": t.artist, "url": t.url, "duration_seconds": t.duration_seconds})
        if not tracks:
            raise HTTPException(400, detail="保存する曲がありません（キューが空）")

        playlist = await db.save_playlist(
            guild_id=req.guild_id, name=req.name,
            created_by=req.requester or "", tracks=tracks,
        )
        return {"success": True, "playlist_id": playlist.id, "name": playlist.name, "track_count": len(playlist.tracks)}

    elif req.action == "load":
        if req.playlist_id is None:
            raise HTTPException(400, detail="playlist_id が必要です")
        vm = voice_module.voice_manager
        if not vm:
            raise HTTPException(503, detail="音楽ボットが準備中です")

        playlist = await db.get_playlist(req.playlist_id)
        if not playlist:
            raise HTTPException(404, detail="プレイリストが見つかりません")
        if not playlist["tracks"]:
            raise HTTPException(400, detail="プレイリストに曲がありません")

        first = playlist["tracks"][0]
        result = await vm.play(
            guild_id=req.guild_id, query=first["url"],
            channel_id=req.channel_id, user_id=req.user_id,
            requester=f"playlist:{playlist['name']}",
        )
        if not result.get("success"):
            raise HTTPException(400, detail=result.get("error"))

        loaded = 1
        for track_data in playlist["tracks"][1:]:
            r = await vm.play(
                guild_id=req.guild_id, query=track_data["url"],
                channel_id=req.channel_id, user_id=req.user_id,
                requester=f"playlist:{playlist['name']}",
            )
            if r.get("success"):
                loaded += 1
        return {"success": True, "tracks_loaded": loaded, "playlist_name": playlist["name"]}

    elif req.action == "delete":
        if req.playlist_id is None:
            raise HTTPException(400, detail="playlist_id が必要です")
        deleted = await db.delete_playlist(req.playlist_id)
        if not deleted:
            raise HTTPException(404, detail="プレイリストが見つかりません")
        return {"success": True}

    else:
        raise HTTPException(400, detail=f"無効なアクション: {req.action}")


@router.get("/{guild_id}")
async def list_playlists(guild_id: str):
    playlists = await db.list_playlists(guild_id)
    return {"playlists": playlists}


@router.post("")
async def save_playlist(req: SavePlaylistRequest):
    vm = voice_module.voice_manager
    if not vm:
        raise HTTPException(503, detail="音楽ボットが準備中です")

    state = vm._state(req.guild_id)
    gq = vm.queue.get(req.guild_id)

    # Collect current track + queue
    tracks = []
    if state.current_track:
        t = state.current_track
        tracks.append({
            "title": t.title,
            "artist": t.artist,
            "url": t.url,
            "duration_seconds": t.duration_seconds,
        })

    for t in gq.tracks:
        tracks.append({
            "title": t.title,
            "artist": t.artist,
            "url": t.url,
            "duration_seconds": t.duration_seconds,
        })

    if not tracks:
        raise HTTPException(400, detail="保存する曲がありません（キューが空）")

    playlist = await db.save_playlist(
        guild_id=req.guild_id,
        name=req.name,
        created_by=req.created_by,
        tracks=tracks,
    )
    return {
        "success": True,
        "playlist_id": playlist.id,
        "name": playlist.name,
        "track_count": len(playlist.tracks),
    }


@router.post("/load")
async def load_playlist(req: LoadPlaylistRequest):
    vm = voice_module.voice_manager
    if not vm:
        raise HTTPException(503, detail="音楽ボットが準備中です")

    playlist = await db.get_playlist(req.playlist_id)
    if not playlist:
        raise HTTPException(404, detail="プレイリストが見つかりません")

    if not playlist["tracks"]:
        raise HTTPException(400, detail="プレイリストに曲がありません")

    # Play first track, queue the rest
    first = playlist["tracks"][0]
    result = await vm.play(
        guild_id=req.guild_id,
        query=first["url"],
        channel_id=req.channel_id,
        user_id=req.user_id,
        requester=f"playlist:{playlist['name']}",
    )

    if not result.get("success"):
        raise HTTPException(400, detail=result.get("error"))

    # Queue remaining tracks
    loaded = 1
    for track_data in playlist["tracks"][1:]:
        r = await vm.play(
            guild_id=req.guild_id,
            query=track_data["url"],
            channel_id=req.channel_id,
            user_id=req.user_id,
            requester=f"playlist:{playlist['name']}",
        )
        if r.get("success"):
            loaded += 1

    return {"success": True, "tracks_loaded": loaded, "playlist_name": playlist["name"]}


@router.delete("/{playlist_id}")
async def delete_playlist(playlist_id: int):
    deleted = await db.delete_playlist(playlist_id)
    if not deleted:
        raise HTTPException(404, detail="プレイリストが見つかりません")
    return {"success": True}
