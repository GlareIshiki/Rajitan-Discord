"""FastAPI routes for persona management"""

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from PIL import Image
import io

from rajitan.storage.persona_models import PersonaCreate, PersonaUpdate
from rajitan.character.identity import update_bot_identity
from rajitan.web.auth import get_current_user
from rajitan.web.server import UPLOADS_DIR, app_state
from rajitan.utils.config import get_config
from rajitan.utils.logger import get_logger

logger = get_logger("web_personas")

router = APIRouter(tags=["personas"])


# ======================================================================
# List / Get
# ======================================================================


@router.get("/guilds/{guild_id}/personas")
async def list_personas(guild_id: str, user=Depends(get_current_user)):
    """List all personas available to a guild (presets + custom)"""
    character_manager = app_state.get("character_manager")
    if not character_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character manager not available",
        )

    personas = await character_manager.get_available_personas(guild_id)

    # Get active persona id for this guild
    active_persona = await character_manager.resolve_persona(guild_id)
    active_id = active_persona.id if active_persona else "preset_default"

    return {
        "personas": [_persona_to_dict(p) for p in personas],
        "active_persona_id": active_id,
    }


@router.get("/guilds/{guild_id}/personas/{persona_id}")
async def get_persona(guild_id: str, persona_id: str, user=Depends(get_current_user)):
    """Get a specific persona"""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    persona = await db_client.get_persona(persona_id)
    if not persona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )

    # Verify accessible to this guild (own guild, preset, or public)
    if persona.guild_id and persona.guild_id != guild_id and not persona.is_public:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )

    return _persona_to_dict(persona)


# ======================================================================
# Active Persona (must be before {persona_id} routes)
# ======================================================================


class SetActivePersonaRequest(BaseModel):
    persona_id: str


@router.put("/guilds/{guild_id}/personas/active")
async def set_active_persona(
    guild_id: str,
    body: SetActivePersonaRequest,
    user=Depends(get_current_user),
):
    """Set the active persona for a guild"""
    character_manager = app_state.get("character_manager")
    if not character_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character manager not available",
        )

    success = await character_manager.set_guild_persona(guild_id, body.persona_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to set active persona. Check that the persona exists.",
        )

    # Update bot Discord identity (nickname + avatar)
    bot = app_state.get("bot")
    if bot:
        persona = await character_manager.resolve_persona(guild_id)
        if persona:
            await update_bot_identity(bot, guild_id, persona)

    return {"status": "ok", "active_persona_id": body.persona_id}


# ======================================================================
# Create / Update / Delete
# ======================================================================


@router.post("/guilds/{guild_id}/personas", status_code=status.HTTP_201_CREATED)
async def create_persona(
    guild_id: str, body: PersonaCreate, user=Depends(get_current_user)
):
    """Create a custom persona for a guild"""
    character_manager = app_state.get("character_manager")
    if not character_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character manager not available",
        )

    created_by = user.get("id", "")
    persona = await character_manager.create_custom_persona(guild_id, created_by, body)
    if not persona:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create persona. Check name uniqueness and guild limit (max 50).",
        )

    return _persona_to_dict(persona)


@router.put("/guilds/{guild_id}/personas/{persona_id}")
async def update_persona(
    guild_id: str,
    persona_id: str,
    body: PersonaUpdate,
    user=Depends(get_current_user),
):
    """Update a custom persona (presets cannot be modified)"""
    character_manager = app_state.get("character_manager")
    if not character_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character manager not available",
        )

    # Verify persona belongs to this guild
    db_client = app_state.get("db_client")
    persona = await db_client.get_persona(persona_id) if db_client else None
    if not persona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )
    if persona.is_preset:
        # Allow only avatar_url updates for presets
        non_avatar_fields = {
            k for k, v in body.model_dump(exclude_unset=True).items()
            if k != "avatar_url" and v is not None
        }
        if non_avatar_fields:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Preset personas cannot be modified (except avatar_url)",
            )
    if not persona.is_preset and persona.guild_id != guild_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )

    success = await character_manager.update_custom_persona(persona_id, body)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update persona",
        )

    updated = await db_client.get_persona(persona_id)
    return _persona_to_dict(updated) if updated else {"status": "ok"}


@router.delete(
    "/guilds/{guild_id}/personas/{persona_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_persona(
    guild_id: str, persona_id: str, user=Depends(get_current_user)
):
    """Delete a custom persona (presets cannot be deleted)"""
    character_manager = app_state.get("character_manager")
    db_client = app_state.get("db_client")
    if not character_manager or not db_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not available",
        )

    persona = await db_client.get_persona(persona_id)
    if not persona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )
    if persona.is_preset:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Preset personas cannot be deleted",
        )
    if persona.guild_id != guild_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )

    success = await character_manager.delete_custom_persona(persona_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete persona",
        )


# ======================================================================
# Avatar Upload / Delete
# ======================================================================

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
AVATAR_PX = 256


@router.post("/personas/{persona_id}/avatar")
async def upload_avatar(
    persona_id: str,
    file: UploadFile,
    user=Depends(get_current_user),
):
    """Upload an avatar image for a persona (presets included)"""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(status_code=503, detail="Database not available")

    persona = await db_client.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {file.content_type}. Use PNG, JPEG, WebP, or GIF.",
        )

    # Read and validate size
    data = await file.read()
    if len(data) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 2MB)")

    # Resize to 256x256 PNG with Pillow
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        img = img.resize((AVATAR_PX, AVATAR_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    # Save to uploads/avatars/{persona_id}.png
    avatars_dir = UPLOADS_DIR / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    dest = avatars_dir / f"{persona_id}.png"
    dest.write_bytes(png_bytes)

    # Build public URL
    config = get_config()
    base = f"https://api.glareishiki.com"
    if config.api_port != 443:
        # Local dev fallback
        base = f"http://{config.api_host}:{config.api_port}"
    avatar_url = f"{base}/uploads/avatars/{persona_id}.png?t={int(time.time())}"

    # Update DB (works for presets too)
    await db_client.update_persona(persona_id, {"avatar_url": avatar_url})

    # Clear cache
    character_manager = app_state.get("character_manager")
    if character_manager:
        character_manager._persona_cache.pop(persona_id, None)

    logger.info(f"Avatar uploaded for persona {persona_id}")
    return {"avatar_url": avatar_url}


@router.delete("/personas/{persona_id}/avatar", status_code=status.HTTP_200_OK)
async def delete_avatar(
    persona_id: str,
    user=Depends(get_current_user),
):
    """Remove the avatar image for a persona"""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(status_code=503, detail="Database not available")

    persona = await db_client.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Delete file if exists
    dest = UPLOADS_DIR / "avatars" / f"{persona_id}.png"
    dest.unlink(missing_ok=True)

    # Clear avatar_url in DB
    await db_client.update_persona(persona_id, {"avatar_url": ""})

    character_manager = app_state.get("character_manager")
    if character_manager:
        character_manager._persona_cache.pop(persona_id, None)

    logger.info(f"Avatar deleted for persona {persona_id}")
    return {"status": "ok"}


# ======================================================================
# Helpers
# ======================================================================


def _persona_to_dict(persona) -> dict:
    """Convert a Persona object to a JSON-serializable dict"""
    return {
        "id": persona.id,
        "guild_id": persona.guild_id,
        "name": persona.name,
        "display_name": persona.display_name,
        "description": persona.description,
        "system_prompt": persona.system_prompt,
        "personality_traits": persona.personality_traits,
        "is_preset": persona.is_preset,
        "is_public": persona.is_public,
        "avatar_url": persona.avatar_url,
        "created_by": persona.created_by,
        "created_at": persona.created_at.isoformat() if persona.created_at else None,
        "updated_at": persona.updated_at.isoformat() if persona.updated_at else None,
    }
