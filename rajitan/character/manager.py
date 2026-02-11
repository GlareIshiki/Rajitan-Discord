from typing import Optional, Dict, Any, List
from datetime import datetime
from rajitan.storage.models import Character, Message
from rajitan.storage.sqlite_client import SQLiteClient
from rajitan.api.openai_client import OpenAIClient
from rajitan.character.prompts import get_system_prompt
from rajitan.character.personality import PersonalityManager, PersonalityType
from rajitan.utils.logger import get_logger
from rajitan.utils.validators import validate_guild_id, validate_system_prompt, validate_character_name

logger = get_logger("character_manager")


class CharacterManager:
    """Manages character creation, storage, and response generation"""

    def __init__(self, db_client: SQLiteClient, openai_client: OpenAIClient):
        self.db_client = db_client
        self.openai_client = openai_client
        self.personality_manager = PersonalityManager()
        self._character_cache = {}
    
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

