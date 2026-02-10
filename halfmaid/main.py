"""HalfMaid entry point — runs Discord bot + FastAPI concurrently."""

import asyncio
import signal
import sys

import uvicorn

from halfmaid.bot.client import HalfMaidBot
from halfmaid.bot import voice as voice_module
from halfmaid.bot.voice import VoiceManager
from halfmaid.queue.manager import QueueManager
from halfmaid.api.server import app as fastapi_app
from halfmaid.config import get_config
from halfmaid.storage.database import PlaylistDatabase
from halfmaid.utils.logger import get_logger

logger = get_logger("main")
config = get_config()


class HalfMaidApplication:
    def __init__(self):
        self.bot: HalfMaidBot | None = None
        self.queue_manager: QueueManager | None = None
        self.running = False

    async def initialize(self):
        if not config.discord_token:
            logger.error("HALFMAID_DISCORD_TOKEN is not set")
            sys.exit(1)

        self.bot = HalfMaidBot()
        self.queue_manager = QueueManager(default_volume=config.default_volume)

        vm = VoiceManager(self.bot, self.queue_manager)
        voice_module.voice_manager = vm

        # Initialize playlist database
        playlist_db = PlaylistDatabase()
        await playlist_db.initialize()

        logger.info("HalfMaid initialized")

    async def start(self):
        if self.running:
            return

        self.running = True
        logger.info("Starting HalfMaid...")

        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host=config.api_host,
            port=config.api_port,
            log_level="info",
        )
        server = uvicorn.Server(uvicorn_config)

        logger.info(f"API server on {config.api_host}:{config.api_port}")

        try:
            await asyncio.gather(
                self.bot.start(config.discord_token),
                server.serve(),
            )
        except Exception as e:
            logger.error(f"Failed to start: {e}")
            await self.shutdown()
            raise

    async def shutdown(self):
        if not self.running:
            return

        logger.info("Shutting down HalfMaid...")
        self.running = False

        # Disconnect all voice clients
        if self.bot:
            for vc in self.bot.voice_clients:
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
            await self.bot.close()

        logger.info("HalfMaid shutdown complete")


app = HalfMaidApplication()


def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    loop = asyncio.get_event_loop()
    loop.create_task(app.shutdown())


async def main():
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        await app.initialize()
        await app.start()
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        await app.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
