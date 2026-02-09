"""FastAPI server for Rajitan WebUI integration"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("web_server")
config = get_config()

# Application state (injected by main.py)
app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: setup and teardown"""
    from rajitan.web.auth import set_redis_client

    redis_client = app_state.get("redis_client")
    if redis_client:
        set_redis_client(redis_client)

    logger.info(f"FastAPI server started on {config.api_host}:{config.api_port}")
    yield
    logger.info("FastAPI server shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="Rajitan API",
        description="API for Rajitan Discord Bot & LeveMagi integration",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check
    @app.get("/api/health")
    async def health():
        bot = app_state.get("bot")
        return {
            "status": "ok",
            "bot_ready": bot.ready if bot else False,
        }

    # Auth check
    from rajitan.web.auth import get_current_user
    from fastapi import Depends

    @app.get("/api/auth/me")
    async def auth_me(user=Depends(get_current_user)):
        return {
            "id": user.get("id"),
            "username": user.get("username"),
            "avatar": user.get("avatar"),
            "global_name": user.get("global_name"),
        }

    # Register routers
    from rajitan.web.routes.levemagi import router as levemagi_router
    from rajitan.web.routes.calendar import router as calendar_router
    from rajitan.web.routes.bot import router as bot_router
    from rajitan.web.routes.google_auth import router as google_router
    from rajitan.web.routes.workflow import router as workflow_router
    from rajitan.web.routes.personas import router as personas_router
    app.include_router(levemagi_router, prefix="/api/levemagi")
    app.include_router(calendar_router, prefix="/api/calendar")
    app.include_router(bot_router, prefix="/api/bot")
    app.include_router(google_router, prefix="/api/google")
    app.include_router(workflow_router, prefix="/api/workflow")
    app.include_router(personas_router, prefix="/api/bot")

    return app
