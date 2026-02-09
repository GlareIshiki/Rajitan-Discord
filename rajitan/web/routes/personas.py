"""FastAPI routes for persona management"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from rajitan.storage.persona_models import PersonaCreate, PersonaUpdate
from rajitan.web.auth import get_current_user
from rajitan.web.server import app_state
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

    # Verify accessible to this guild
    if persona.guild_id and persona.guild_id != guild_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )

    return _persona_to_dict(persona)


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Preset personas cannot be modified",
        )
    if persona.guild_id != guild_id:
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
# Active Persona
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

    return {"status": "ok", "active_persona_id": body.persona_id}


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
        "created_by": persona.created_by,
        "created_at": persona.created_at.isoformat() if persona.created_at else None,
        "updated_at": persona.updated_at.isoformat() if persona.updated_at else None,
    }
