from fastapi import APIRouter, Query

from halfmaid.utils.ytdlp import YtDlpExtractor
from halfmaid.utils.logger import get_logger

logger = get_logger("api.search")
router = APIRouter()
extractor = YtDlpExtractor()


@router.get("/search")
async def search(
    q: str = Query(..., description="Search query"),
    source: str = Query("youtube", description="Search source: youtube or spotify"),
    limit: int = Query(5, ge=1, le=10),
):
    if source == "spotify":
        # Spotify search: prepend artist/track context for yt-dlp
        # TODO: Use Spotify API for richer search, then resolve via YouTube
        pass

    results = await extractor.search(q, limit=limit)
    return {
        "results": [
            {
                "title": r.title,
                "artist": r.artist,
                "url": r.url,
                "duration_seconds": r.duration_seconds,
                "source": "youtube",
                "thumbnail": r.thumbnail,
            }
            for r in results
        ]
    }
