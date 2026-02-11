"""PersonaManager — all persona business logic in one place.

Extracted from CharacterManager to give personas a clear vertical slice:
  storage/persona_repo.py (DB) → persona/manager.py (logic) → persona/identity.py (Discord)
"""

import time
import random
from typing import Dict, List, Optional

from rajitan.character.prompts import DEFAULT_SYSTEM_PROMPT
from rajitan.character.personality import PersonalityManager
from rajitan.storage.persona_models import Persona, PersonaCreate, PersonaUpdate
from rajitan.utils.logger import get_logger

logger = get_logger("persona.manager")

MAX_CUSTOM_PERSONAS_PER_GUILD = 50


class PersonaManager:
    """Manages persona resolution, CRUD, and caching."""

    def __init__(self, db_client, character_manager=None):
        self.db_client = db_client
        self.character_manager = character_manager
        self._persona_cache: Dict[str, Persona] = {}
        self._personality_manager = PersonalityManager()

    async def resolve_persona(self, guild_id: str) -> Optional[Persona]:
        """Resolve the effective persona for a guild.

        Priority:
          1. characters.active_persona_id (via persona_repo)
          2. characters.personality_traits.type → corresponding preset
          3. preset_default
        """
        try:
            # 1. active_persona_id from DB
            active_id = await self.db_client.persona.get_guild_active_persona_id(guild_id)
            if active_id:
                persona = await self._get_cached_persona(active_id)
                if persona:
                    return persona

            # 2. Legacy personality_traits.type → preset
            if self.character_manager:
                character = await self.character_manager.get_character(guild_id)
                if character and character.personality_traits:
                    ptype = character.personality_traits.get("type", "")
                    if ptype:
                        preset_id = f"preset_{ptype}"
                        persona = await self._get_cached_persona(preset_id)
                        if persona:
                            return persona

            # 3. Fallback: preset_default
            return await self._get_cached_persona("preset_default")

        except Exception as e:
            logger.error(f"Failed to resolve persona for guild {guild_id}: {e}")
            return await self._get_cached_persona("preset_default")

    async def _get_cached_persona(self, persona_id: str) -> Optional[Persona]:
        """Get persona with cache."""
        if persona_id in self._persona_cache:
            return self._persona_cache[persona_id]
        persona = await self.db_client.persona.get_persona(persona_id)
        if persona:
            self._persona_cache[persona_id] = persona
        return persona

    async def get_available_personas(self, guild_id: str) -> List[Persona]:
        """Get all personas available to a guild (presets + custom)."""
        return await self.db_client.persona.get_guild_personas(guild_id)

    async def set_guild_persona(self, guild_id: str, persona_id: str) -> bool:
        """Set the guild's active persona."""
        success = await self.db_client.persona.set_guild_active_persona(guild_id, persona_id)
        if success:
            self._persona_cache.pop(persona_id, None)
        return success

    async def create_custom_persona(
        self, guild_id: str, created_by: str, data: PersonaCreate
    ) -> Optional[Persona]:
        """Create a custom persona for a guild."""
        try:
            name = (data.name or "").strip()
            if not name or len(name) > 32:
                logger.error("Persona name must be 1-32 characters")
                return None

            count = await self.db_client.persona.count_guild_personas(guild_id)
            if count >= MAX_CUSTOM_PERSONAS_PER_GUILD:
                logger.error(f"Guild {guild_id} has reached the persona limit ({MAX_CUSTOM_PERSONAS_PER_GUILD})")
                return None

            existing = await self.db_client.persona.get_guild_personas(guild_id)
            for p in existing:
                if p.guild_id == guild_id and p.name == name:
                    logger.error(f"Persona name '{name}' already exists in guild {guild_id}")
                    return None

            traits = data.personality_traits or {
                "friendliness": 0.8,
                "humor": 0.7,
                "energy": 0.6,
                "formality": 0.3,
                "helpfulness": 0.9,
            }
            traits = {k: max(0.0, min(1.0, v)) for k, v in traits.items()}

            system_prompt = (data.system_prompt or "").strip()
            if not system_prompt:
                base = DEFAULT_SYSTEM_PROMPT
                system_prompt = self._personality_manager.customize_prompt_for_traits(
                    base, traits
                )

            if len(system_prompt) > 4000:
                logger.error("System prompt exceeds 4000 characters")
                return None

            persona_id = f"{int(time.time() * 1000):x}{random.getrandbits(32):08x}"

            persona = Persona(
                id=persona_id,
                guild_id=guild_id,
                name=name,
                display_name=(data.display_name or "").strip()[:64],
                description=(data.description or "").strip()[:200],
                system_prompt=system_prompt,
                personality_traits=traits,
                is_preset=False,
                is_public=data.is_public,
                avatar_url=(data.avatar_url or "").strip(),
                created_by=created_by,
            )

            success = await self.db_client.persona.create_persona(persona)
            if success:
                self._persona_cache[persona_id] = persona
                logger.info(f"Custom persona '{name}' created for guild {guild_id}")
                return persona
            return None

        except Exception as e:
            logger.error(f"Failed to create custom persona: {e}")
            return None

    async def update_custom_persona(
        self, persona_id: str, data: PersonaUpdate
    ) -> bool:
        """Update a custom persona."""
        try:
            updates = {}
            if data.name is not None:
                name = data.name.strip()
                if not name or len(name) > 32:
                    return False
                updates["name"] = name
            if data.display_name is not None:
                updates["display_name"] = data.display_name.strip()[:64]
            if data.description is not None:
                updates["description"] = data.description.strip()[:200]
            if data.system_prompt is not None:
                sp = data.system_prompt.strip()
                if len(sp) > 4000:
                    return False
                updates["system_prompt"] = sp
            if data.personality_traits is not None:
                updates["personality_traits"] = {
                    k: max(0.0, min(1.0, v))
                    for k, v in data.personality_traits.items()
                }
            if data.is_public is not None:
                updates["is_public"] = data.is_public
            if data.avatar_url is not None:
                updates["avatar_url"] = data.avatar_url.strip()

            if not updates:
                return False

            success = await self.db_client.persona.update_persona(persona_id, updates)
            if success:
                self._persona_cache.pop(persona_id, None)
            return success

        except Exception as e:
            logger.error(f"Failed to update custom persona: {e}")
            return False

    async def delete_custom_persona(self, persona_id: str) -> bool:
        """Delete a custom persona."""
        success = await self.db_client.persona.delete_persona(persona_id)
        if success:
            self._persona_cache.pop(persona_id, None)
        return success
