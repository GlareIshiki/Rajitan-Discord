from fastapi import APIRouter

from halfmaid.bot import voice as voice_module

router = APIRouter()


@router.get("/health")
async def health():
    vm = voice_module.voice_manager
    if not vm:
        return {"status": "starting", "bot_ready": False}

    bot = vm.bot
    return {
        "status": "ok",
        "bot_ready": bot.is_ready(),
        "connected_guilds": len(bot.guilds),
        "voice_connections": sum(
            1 for g in bot.guilds if g.voice_client and g.voice_client.is_connected()
        ),
    }


@router.get("/status/{guild_id}")
async def guild_status(guild_id: str):
    vm = voice_module.voice_manager
    if not vm:
        return {"connected": False, "error": "Bot not ready"}
    return vm.get_status(guild_id)
