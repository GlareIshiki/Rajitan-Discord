import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from rajitan.storage.models import Character, Message
from rajitan.storage.sqlite_client import SQLiteClient
from rajitan.storage.persona_models import Persona, PersonaCreate, PersonaUpdate
from rajitan.api.openai_client import OpenAIClient
from rajitan.character.prompts import get_system_prompt, DEFAULT_SYSTEM_PROMPT
from rajitan.character.personality import PersonalityManager, PersonalityType
from rajitan.utils.logger import get_logger
from rajitan.utils.validators import validate_guild_id, validate_system_prompt, validate_character_name

logger = get_logger("character_manager")

MAX_CUSTOM_PERSONAS_PER_GUILD = 50


class CharacterManager:
    """Manages character creation, storage, and response generation"""

    def __init__(self, db_client: SQLiteClient, openai_client: OpenAIClient):
        self.db_client = db_client
        self.openai_client = openai_client
        self.personality_manager = PersonalityManager()
        self._character_cache = {}
        self._persona_cache: Dict[str, Persona] = {}
    
    async def create_character(
        self, 
        guild_id: str, 
        name: str = "らじたん", 
        system_prompt: Optional[str] = None,
        personality_type: str = "default"
    ) -> bool:
        """Create or update a character for a guild"""
        try:
            # Validate inputs
            if not validate_guild_id(guild_id):
                logger.error(f"Invalid guild ID: {guild_id}")
                return False
            
            if not validate_character_name(name):
                logger.error(f"Invalid character name: {name}")
                return False
            
            # Use default system prompt if not provided
            if not system_prompt:
                system_prompt = get_system_prompt(name, personality_type)
            elif not validate_system_prompt(system_prompt):
                logger.error(f"Invalid system prompt")
                return False
            
            # Customize prompt based on personality
            final_prompt = self.personality_manager.customize_prompt_for_personality(
                system_prompt, personality_type
            )
            
            # Create personality traits
            personality_traits = {
                "type": personality_type,
                "traits": self.personality_manager.get_personality_traits(personality_type)
            }
            
            # Create character object
            character = Character(
                guild_id=guild_id,
                name=name,
                system_prompt=final_prompt,
                personality_traits=personality_traits,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            
            # Save to database
            success = await self.db_client.create_character(character)
            if success:
                # Update cache
                self._character_cache[guild_id] = character
                logger.info(f"Character '{name}' created/updated for guild {guild_id}")
                return True
            else:
                logger.error(f"Failed to save character to database")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create character: {e}")
            return False
    
    async def get_character(self, guild_id: str) -> Optional[Character]:
        """Get character for a guild"""
        try:
            if not validate_guild_id(guild_id):
                return None
            
            # Check cache first
            if guild_id in self._character_cache:
                return self._character_cache[guild_id]
            
            # Get from database
            character = await self.db_client.get_character(guild_id)
            if character:
                # Update cache
                self._character_cache[guild_id] = character
            
            return character
            
        except Exception as e:
            logger.error(f"Failed to get character: {e}")
            return None
    
    async def update_character(
        self, 
        guild_id: str, 
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        personality_type: Optional[str] = None
    ) -> bool:
        """Update an existing character"""
        try:
            # Get existing character
            character = await self.get_character(guild_id)
            if not character:
                logger.error(f"Character not found for guild {guild_id}")
                return False
            
            # Update fields
            updated = False
            
            if name and validate_character_name(name):
                character.name = name
                updated = True
            
            if system_prompt and validate_system_prompt(system_prompt):
                character.system_prompt = system_prompt
                updated = True
            
            if personality_type and personality_type in PersonalityType:
                if not character.personality_traits:
                    character.personality_traits = {}
                character.personality_traits["type"] = personality_type
                character.personality_traits["traits"] = self.personality_manager.get_personality_traits(personality_type)
                
                # Re-customize prompt
                character.system_prompt = self.personality_manager.customize_prompt_for_personality(
                    character.system_prompt, personality_type
                )
                updated = True
            
            if updated:
                character.updated_at = datetime.now()
                success = await self.db_client.create_character(character)
                if success:
                    # Update cache
                    self._character_cache[guild_id] = character
                    logger.info(f"Character updated for guild {guild_id}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update character: {e}")
            return False
    
    async def update_character_personality(
        self, 
        guild_id: str, 
        personality_type: str,
        system_prompt: Optional[str] = None
    ) -> bool:
        """Update character personality and optionally system prompt"""
        try:
            # Get existing character
            character = await self.get_character(guild_id)
            if not character:
                logger.error(f"Character not found for guild {guild_id}")
                return False
            
            # Update personality type
            if not character.personality_traits:
                character.personality_traits = {}
            
            character.personality_traits["type"] = personality_type
            character.personality_traits["traits"] = self.personality_manager.get_personality_traits(personality_type)
            
            # Update system prompt
            if system_prompt and validate_system_prompt(system_prompt):
                character.system_prompt = system_prompt
            else:
                # Generate fresh prompt for the new personality type
                character.system_prompt = get_system_prompt(character.name, personality_type)
            
            character.updated_at = datetime.now()
            
            # Save to database
            success = await self.db_client.create_character(character)
            if success:
                # Update cache
                self._character_cache[guild_id] = character
                logger.info(f"Character personality updated for guild {guild_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update character personality: {e}")
            return False
    
    async def generate_response(
        self, 
        guild_id: str, 
        messages: List[Message], 
        user_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Generate character response to user message"""
        try:
            # Get character
            character = await self.get_character(guild_id)
            if not character:
                logger.error(f"No character found for guild {guild_id}")
                return None
            
            # Get personality type
            personality_type = "default"
            if character.personality_traits and "type" in character.personality_traits:
                personality_type = character.personality_traits["type"]
            
            # Calculate response style based on personality and context
            style_params = self.personality_manager.calculate_response_style(
                personality_type, context or {}
            )
            
            # Generate response using OpenAI
            response = await self.openai_client.generate_character_response(
                system_prompt=character.system_prompt,
                messages=messages,
                user_message=user_message,
                max_tokens=style_params.get("max_tokens", 300)
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            return None
    
    async def should_use_feature(
        self, 
        guild_id: str, 
        feature: str, 
        context: Dict[str, Any]
    ) -> bool:
        """Determine if character should use a specific feature"""
        try:
            character = await self.get_character(guild_id)
            if not character:
                return False
            
            personality_type = "default"
            if character.personality_traits and "type" in character.personality_traits:
                personality_type = character.personality_traits["type"]
            
            return self.personality_manager.should_use_feature(
                personality_type, feature, context
            )
            
        except Exception as e:
            logger.error(f"Failed to check feature usage: {e}")
            return False
    
    async def get_feature_timing(self, guild_id: str, feature: str) -> int:
        """Get timing preference for features"""
        try:
            character = await self.get_character(guild_id)
            if not character:
                return 30  # Default timing
            
            personality_type = "default"
            if character.personality_traits and "type" in character.personality_traits:
                personality_type = character.personality_traits["type"]
            
            return self.personality_manager.get_feature_timing(personality_type, feature)
            
        except Exception as e:
            logger.error(f"Failed to get feature timing: {e}")
            return 30
    
    async def get_character_info(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get character information for display"""
        try:
            character = await self.get_character(guild_id)
            if not character:
                return None
            
            personality_type = "default"
            personality_traits = {}
            
            if character.personality_traits:
                personality_type = character.personality_traits.get("type", "default")
                personality_traits = character.personality_traits.get("traits", {})
            
            return {
                "name": character.name,
                "personality_type": personality_type,
                "personality_traits": personality_traits,
                "created_at": character.created_at,
                "updated_at": character.updated_at
            }
            
        except Exception as e:
            logger.error(f"Failed to get character info: {e}")
            return None
    
    def clear_cache(self):
        """Clear character cache"""
        self._character_cache.clear()
    
    async def delete_character(self, guild_id: str) -> bool:
        """Delete character for a guild"""
        try:
            # Note: This would require implementing delete in SQLiteClient
            # For now, we can just clear from cache
            if guild_id in self._character_cache:
                del self._character_cache[guild_id]

            logger.info(f"Character deleted for guild {guild_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete character: {e}")
            return False

    # --- Persona operations ---

    async def resolve_persona(self, guild_id: str) -> Optional[Persona]:
        """Resolve the effective persona for a guild.

        Priority:
          1. characters.active_persona_id
          2. characters.personality_traits.type → corresponding preset
          3. preset_default
        """
        try:
            character = await self.get_character(guild_id)

            # 1. active_persona_id
            if character:
                active_id = getattr(character, "active_persona_id", None) or (
                    character.personality_traits.get("active_persona_id", "")
                    if character.personality_traits else ""
                )
                if not active_id and hasattr(character, "__dict__"):
                    active_id = ""
                # Try reading from DB directly for the new column
                if not active_id:
                    try:
                        import aiosqlite, json as _json
                        async with aiosqlite.connect(self.db_client.db_path) as db:
                            async with db.execute(
                                "SELECT active_persona_id FROM characters WHERE guild_id = ?",
                                (guild_id,),
                            ) as cursor:
                                row = await cursor.fetchone()
                                if row and row[0]:
                                    active_id = row[0]
                    except Exception:
                        pass

                if active_id:
                    persona = await self._get_cached_persona(active_id)
                    if persona:
                        return persona

            # 2. Legacy personality_traits.type → preset
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
        """Get persona with cache"""
        if persona_id in self._persona_cache:
            return self._persona_cache[persona_id]
        persona = await self.db_client.get_persona(persona_id)
        if persona:
            self._persona_cache[persona_id] = persona
        return persona

    async def get_available_personas(self, guild_id: str) -> List[Persona]:
        """Get all personas available to a guild (presets + custom)"""
        return await self.db_client.get_guild_personas(guild_id)

    async def set_guild_persona(self, guild_id: str, persona_id: str) -> bool:
        """Set the guild's default persona"""
        success = await self.db_client.set_guild_active_persona(guild_id, persona_id)
        if success:
            # Invalidate caches
            self._character_cache.pop(guild_id, None)
            self._persona_cache.pop(persona_id, None)
        return success

    async def create_custom_persona(
        self, guild_id: str, created_by: str, data: PersonaCreate
    ) -> Optional[Persona]:
        """Create a custom persona for a guild"""
        try:
            # Validate name
            name = (data.name or "").strip()
            if not name or len(name) > 32:
                logger.error("Persona name must be 1-32 characters")
                return None

            # Check limit
            count = await self.db_client.count_guild_personas(guild_id)
            if count >= MAX_CUSTOM_PERSONAS_PER_GUILD:
                logger.error(f"Guild {guild_id} has reached the persona limit ({MAX_CUSTOM_PERSONAS_PER_GUILD})")
                return None

            # Check name uniqueness within guild
            existing = await self.db_client.get_guild_personas(guild_id)
            for p in existing:
                if p.guild_id == guild_id and p.name == name:
                    logger.error(f"Persona name '{name}' already exists in guild {guild_id}")
                    return None

            # Clamp traits to 0.0-1.0
            traits = data.personality_traits or {
                "friendliness": 0.8,
                "humor": 0.7,
                "energy": 0.6,
                "formality": 0.3,
                "helpfulness": 0.9,
            }
            traits = {k: max(0.0, min(1.0, v)) for k, v in traits.items()}

            # Build system_prompt if not provided
            system_prompt = (data.system_prompt or "").strip()
            if not system_prompt:
                base = DEFAULT_SYSTEM_PROMPT
                system_prompt = self.personality_manager.customize_prompt_for_traits(
                    base, traits
                )

            # Validate system_prompt length
            if len(system_prompt) > 4000:
                logger.error("System prompt exceeds 4000 characters")
                return None

            import time, random
            persona_id = (
                f"{int(time.time() * 1000):x}{random.getrandbits(32):08x}"
            )

            persona = Persona(
                id=persona_id,
                guild_id=guild_id,
                name=name,
                display_name=(data.display_name or "").strip()[:64],
                description=(data.description or "").strip()[:200],
                system_prompt=system_prompt,
                personality_traits=traits,
                is_preset=False,
                created_by=created_by,
            )

            success = await self.db_client.create_persona(persona)
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
        """Update a custom persona"""
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

            if not updates:
                return False

            success = await self.db_client.update_persona(persona_id, updates)
            if success:
                self._persona_cache.pop(persona_id, None)
            return success

        except Exception as e:
            logger.error(f"Failed to update custom persona: {e}")
            return False

    async def delete_custom_persona(self, persona_id: str) -> bool:
        """Delete a custom persona"""
        success = await self.db_client.delete_persona(persona_id)
        if success:
            self._persona_cache.pop(persona_id, None)
        return success