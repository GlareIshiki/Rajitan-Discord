"""FastAPI server for HalfMaid REST API."""

from fastapi import FastAPI

from halfmaid.api.routes import player, playlist, queue, search, status

app = FastAPI(title="HalfMaid API", version="1.0.0")

app.include_router(status.router, prefix="/api", tags=["status"])
app.include_router(player.router, prefix="/api/player", tags=["player"])
app.include_router(queue.router, prefix="/api/queue", tags=["queue"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(playlist.router, prefix="/api/playlists", tags=["playlists"])
