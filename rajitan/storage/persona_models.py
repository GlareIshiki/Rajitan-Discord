"""Persona data models for the expanded personality system"""

from datetime import datetime
from typing import Optional, Dict
from pydantic import BaseModel, Field


class Persona(BaseModel):
    """A persona definition (preset or custom)"""
    id: str                                             # "preset_default" or generated ID
    guild_id: str = ""                                  # "" = preset, guild_id = custom
    name: str                                           # Unique name within guild
    display_name: str = ""                              # Japanese display name
    description: str = ""                               # Short description
    system_prompt: str = ""                             # Free-form system prompt
    personality_traits: Dict[str, float] = Field(       # {friendliness, humor, energy, formality, helpfulness}
        default_factory=lambda: {
            "friendliness": 0.8,
            "humor": 0.7,
            "energy": 0.6,
            "formality": 0.3,
            "helpfulness": 0.9,
        }
    )
    is_preset: bool = False
    is_public: bool = False                             # True = visible to all guilds
    created_by: str = ""                                # Discord user ID
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PersonaCreate(BaseModel):
    """Request body for creating a custom persona"""
    name: str
    display_name: str = ""
    description: str = ""
    system_prompt: str = ""
    personality_traits: Optional[Dict[str, float]] = None
    is_public: bool = False


class PersonaUpdate(BaseModel):
    """Request body for updating a custom persona"""
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    personality_traits: Optional[Dict[str, float]] = None
    is_public: Optional[bool] = None
