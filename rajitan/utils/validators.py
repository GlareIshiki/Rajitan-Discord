import re
from typing import Optional, Union


def validate_discord_id(discord_id: Union[str, int]) -> bool:
    """Validate Discord ID format"""
    try:
        discord_id = str(discord_id)
        return discord_id.isdigit() and len(discord_id) >= 17 and len(discord_id) <= 19
    except:
        return False


def validate_channel_id(channel_id: Union[str, int]) -> bool:
    """Validate Discord channel ID format"""
    return validate_discord_id(channel_id)


def validate_guild_id(guild_id: Union[str, int]) -> bool:
    """Validate Discord guild ID format"""
    return validate_discord_id(guild_id)


def validate_user_id(user_id: Union[str, int]) -> bool:
    """Validate Discord user ID format"""
    return validate_discord_id(user_id)


def validate_system_prompt(prompt: str) -> bool:
    """Validate system prompt format"""
    if not prompt or not isinstance(prompt, str):
        return False
    
    # Check length (max 2000 characters)
    if len(prompt) > 2000:
        return False
    
    # Check for basic content
    if len(prompt.strip()) < 10:
        return False
    
    return True


def validate_interval(interval: int) -> bool:
    """Validate interval setting (in minutes)"""
    return isinstance(interval, int) and 5 <= interval <= 1440  # 5 minutes to 24 hours


def validate_message_content(content: str) -> bool:
    """Validate message content"""
    if not content or not isinstance(content, str):
        return False
    
    # Check length (Discord limit is 2000 characters)
    if len(content) > 2000:
        return False
    
    return True


def sanitize_input(text: str) -> str:
    """Sanitize user input"""
    if not text:
        return ""
    
    # Remove control characters
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    # Trim whitespace
    text = text.strip()
    
    return text


def validate_character_name(name: str) -> bool:
    """Validate character name"""
    if not name or not isinstance(name, str):
        return False

    # Check length
    if len(name) < 1 or len(name) > 32:
        return False

    # Reject control characters only (allow Unicode including Japanese)
    if re.search(r'[\x00-\x1f\x7f-\x9f]', name):
        return False

    return True