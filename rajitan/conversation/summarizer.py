import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from rajitan.storage.models import Message, SummaryData
from rajitan.api.openai_client import OpenAIClient
from rajitan.character.manager import CharacterManager
from rajitan.utils.logger import get_logger

logger = get_logger("conversation_summarizer")


class ConversationSummarizer:
    """Handles conversation summarization with character personality"""
    
    def __init__(self, openai_client: OpenAIClient, character_manager: CharacterManager):
        self.openai_client = openai_client
        self.character_manager = character_manager
    
    async def generate_summary(
        self, 
        guild_id: str,
        channel_id: str, 
        messages: List[Message],
        custom_context: Optional[Dict[str, Any]] = None
    ) -> Optional[SummaryData]:
        """Generate conversation summary with character personality"""
        try:
            if not messages:
                logger.warning("No messages to summarize")
                return None
            
            # Get character for personalized summary
            character = await self.character_manager.get_character(guild_id)
            character_name = character.name if character else "らじたん"
            
            # Generate summary using OpenAI
            summary_text = await self.openai_client.generate_summary(messages, character_name)
            
            if not summary_text:
                logger.error("Failed to generate summary text")
                return None
            
            # Extract participants
            participants = list(set(msg.user_id for msg in messages))
            
            # Create summary data
            summary_data = SummaryData(
                channel_id=channel_id,
                content=summary_text,
                message_count=len(messages),
                participants=participants,
                created_at=datetime.now()
            )
            
            logger.info(f"Summary generated for channel {channel_id}: {len(messages)} messages")
            return summary_data
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return None
    
    async def should_summarize(
        self, 
        guild_id: str,
        messages: List[Message], 
        context: Dict[str, Any]
    ) -> bool:
        """Determine if conversation should be summarized based on character personality"""
        try:
            if not messages:
                return False
            
            # Check character preference for summarization
            should_use = await self.character_manager.should_use_feature(
                guild_id, "summary", context
            )
            
            if not should_use:
                return False
            
            # Additional checks
            message_count = len(messages)
            activity_level = context.get("activity", {}).get("activity_level", "inactive")
            
            # Don't summarize if conversation is too short
            if message_count < 10:
                return False
            
            # Don't summarize if conversation is very active (might interrupt)
            if activity_level == "very_high":
                return False
            
            # Summarize if conversation is cooling down or has many messages
            if activity_level in ["low", "medium"] or message_count >= 30:
                return True
            
            # Check if conversation seems to be ending
            is_ending = context.get("is_ending", False)
            if is_ending and message_count >= 15:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check summarization need: {e}")
            return False
    
    async def format_summary_for_discord(
        self, 
        summary_data: SummaryData,
        include_stats: bool = True
    ) -> str:
        """Format summary for Discord display"""
        try:
            formatted_summary = summary_data.content
            
            if include_stats:
                stats_text = (
                    f"\n\n📊 **会話の統計**\n"
                    f"💬 メッセージ数: {summary_data.message_count}\n"
                    f"👥 参加者数: {len(summary_data.participants)}\n"
                    f"🕰 作成時刻: {summary_data.created_at.strftime('%H:%M')}"
                )
                formatted_summary += stats_text
            
            return formatted_summary
            
        except Exception as e:
            logger.error(f"Failed to format summary: {e}")
            return summary_data.content
    
    async def get_summary_timing(self, guild_id: str) -> int:
        """Get preferred timing for summaries based on character"""
        try:
            timing = await self.character_manager.get_feature_timing(guild_id, "summary")
            return timing
            
        except Exception as e:
            logger.error(f"Failed to get summary timing: {e}")
            return 30  # Default 30 minutes
    
    async def create_summary_prompt(
        self, 
        guild_id: str,
        messages: List[Message], 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create customized summary prompt based on character and context"""
        try:
            character = await self.character_manager.get_character(guild_id)
            character_name = character.name if character else "らじたん"
            
            # Base prompt
            prompt = f"""
あなたは{character_name}として、この会話を要約してください。

要約の観点：
- 主要な話の流れを3点程度にまとめ
- 参加者の雰囲気を表現する
- ラジオDJの視点で楽しく
- その会話のまとめとして適切に
- 聞き手が分かりやすい内容にする
"""
            
            # Add context-specific instructions
            if context:
                topics = context.get("topics", [])
                if topics:
                    prompt += f"\n主要な話題: {', '.join(topics)}"
                
                sentiment = context.get("sentiment")
                if sentiment:
                    if sentiment == "positive":
                        prompt += "\n会話は楽しい雰囲気でした"
                    elif sentiment == "excited":
                        prompt += "\n会話は興奮した盛り上がりでした"
                    elif sentiment == "relaxed":
                        prompt += "\n会話はリラックスした落ち着いた雰囲気でした"
            
            return prompt
            
        except Exception as e:
            logger.error(f"Failed to create summary prompt: {e}")
            return "会話を要約してください。"
    
    async def validate_summary_quality(self, summary: str) -> bool:
        """Validate summary quality"""
        try:
            if not summary or len(summary.strip()) < 20:
                return False
            
            # Check for minimum content
            if len(summary) < 50:
                return False
            
            # Check for maximum length (Discord message limit)
            if len(summary) > 1800:  # Leave room for stats
                return False
            
            # Check for obvious errors or repetition
            words = summary.split()
            if len(set(words)) < len(words) * 0.6:  # Too much repetition
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to validate summary quality: {e}")
            return False