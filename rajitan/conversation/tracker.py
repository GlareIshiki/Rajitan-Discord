import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from rajitan.storage.models import Conversation, Message, ActiveSession, ConversationState
from rajitan.storage.redis_client import RedisClient
from rajitan.conversation.analyzer import ConversationAnalyzer
from rajitan.utils.logger import get_logger
from rajitan.utils.validators import validate_channel_id, validate_user_id, validate_message_content
from rajitan.utils.decorators import handle_async_errors

logger = get_logger("conversation_tracker")


class ConversationTracker:
    """Tracks and manages conversation state across Discord channels"""
    
    def __init__(self, redis_client: RedisClient, conversation_analyzer: ConversationAnalyzer):
        self.redis_client = redis_client
        self.conversation_analyzer = conversation_analyzer
        self.conversation_timeout = 3600  # 1 hour timeout
    
    @handle_async_errors(operation_name="track message", default_return=False)
    async def track_message(
        self, 
        channel_id: str, 
        user_id: str, 
        username: str, 
        content: str
    ) -> bool:
        """Track a new message in the conversation"""
        # Validate inputs
        if not validate_channel_id(channel_id):
            logger.error(f"Invalid channel ID: {channel_id}")
            return False
        
        if not validate_user_id(user_id):
            logger.error(f"Invalid user ID: {user_id}")
            return False
        
        if not validate_message_content(content):
            logger.error(f"Invalid message content")
            return False
        
        # Create message object
        message = Message(
            user_id=user_id,
            username=username,
            content=content,
            timestamp=datetime.now()
        )
        
        # Add message to conversation
        success = await self.redis_client.add_message_to_conversation(channel_id, message)
        if not success:
            logger.error(f"Failed to add message to conversation")
            return False
        
        # Update active session
        await self._update_active_session(channel_id, user_id)
        
        logger.debug(f"Message tracked for channel {channel_id}")
        return True
    
    async def _update_active_session(self, channel_id: str, user_id: str):
        """Update active session information"""
        try:
            session = await self.redis_client.get_active_session(channel_id)
            
            if session is None:
                session = ActiveSession(
                    channel_id=channel_id,
                    last_activity=datetime.now(),
                    message_count=1,
                    participants=[user_id]
                )
            else:
                session.last_activity = datetime.now()
                session.message_count += 1
                if user_id not in session.participants:
                    session.participants.append(user_id)
            
            await self.redis_client.store_active_session(session)
            
        except Exception as e:
            logger.error(f"Failed to update active session: {e}")
    
    @handle_async_errors(operation_name="get recent conversation", default_return=[])
    async def get_recent_conversation(
        self, 
        channel_id: str, 
        duration_minutes: int = 60
    ) -> List[Message]:
        """Get recent messages from conversation"""
        if not validate_channel_id(channel_id):
            return []
        
        messages = await self.redis_client.get_recent_messages(channel_id, duration_minutes)
        return messages
    
    async def get_full_conversation(self, channel_id: str) -> Optional[Conversation]:
        """Get full conversation from Redis"""
        try:
            if not validate_channel_id(channel_id):
                return None
            
            conversation = await self.redis_client.get_conversation(channel_id)
            return conversation
            
        except Exception as e:
            logger.error(f"Failed to get full conversation: {e}")
            return None
    
    async def is_conversation_active(
        self, 
        channel_id: str, 
        timeout_minutes: int = 30
    ) -> bool:
        """Check if conversation is currently active"""
        try:
            if not validate_channel_id(channel_id):
                return False
            
            return await self.redis_client.is_conversation_active(channel_id, timeout_minutes)
            
        except Exception as e:
            logger.error(f"Failed to check conversation activity: {e}")
            return False
    
    async def get_conversation_state(self, channel_id: str) -> ConversationState:
        """Get current conversation state"""
        try:
            conversation = await self.get_full_conversation(channel_id)
            if not conversation:
                return ConversationState.INACTIVE
            
            # Check if conversation is active
            is_active = await self.is_conversation_active(channel_id)
            if not is_active:
                return ConversationState.INACTIVE
            
            # Analyze conversation to determine state
            activity = await self.conversation_analyzer.analyze_conversation_activity(
                conversation.messages
            )
            
            activity_level = activity.get("activity_level", "inactive")
            
            if activity_level in ["very_high", "high"]:
                return ConversationState.ACTIVE
            elif activity_level in ["medium", "low"]:
                return ConversationState.COOLING_DOWN
            else:
                return ConversationState.INACTIVE
            
        except Exception as e:
            logger.error(f"Failed to get conversation state: {e}")
            return ConversationState.INACTIVE
    
    async def mark_conversation_end(self, channel_id: str) -> bool:
        """Mark conversation as ended"""
        try:
            if not validate_channel_id(channel_id):
                return False
            
            # Clear active session
            await self.redis_client.delete_cache(f"session:{channel_id}")
            
            # Update conversation state
            conversation = await self.get_full_conversation(channel_id)
            if conversation:
                conversation.state = ConversationState.INACTIVE
                await self.redis_client.store_conversation(conversation)
            
            logger.info(f"Conversation ended for channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to mark conversation end: {e}")
            return False
    
    @handle_async_errors(operation_name="get conversation summary data", default_return=None)
    async def get_conversation_summary_data(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get data needed for conversation summary"""
        conversation = await self.get_full_conversation(channel_id)
        if not conversation or not conversation.messages:
            return None
        
        # Get conversation context
        context = await self.conversation_analyzer.get_conversation_context(
            conversation.messages
        )
        
        return {
            "messages": conversation.messages,
            "participant_count": len(conversation.participants),
            "message_count": len(conversation.messages),
            "start_time": conversation.messages[0].timestamp if conversation.messages else None,
            "end_time": conversation.messages[-1].timestamp if conversation.messages else None,
            "topics": context.get("topics", []),
            "sentiment": context.get("sentiment"),
            "activity_level": context.get("activity", {}).get("activity_level")
        }
    
    async def should_execute_feature(
        self, 
        channel_id: str, 
        feature_type: str
    ) -> bool:
        """Determine if a feature should be executed based on conversation state"""
        try:
            conversation = await self.get_full_conversation(channel_id)
            if not conversation or not conversation.messages:
                return False
            
            # Get conversation context
            context = await self.conversation_analyzer.get_conversation_context(
                conversation.messages
            )
            
            # Check if feature should intervene
            should_intervene = await self.conversation_analyzer.should_intervene(
                conversation.messages, feature_type, context
            )
            
            return should_intervene
            
        except Exception as e:
            logger.error(f"Failed to check feature execution: {e}")
            return False
    
    async def get_conversation_stats(self, channel_id: str) -> Dict[str, Any]:
        """Get conversation statistics"""
        try:
            conversation = await self.get_full_conversation(channel_id)
            session = await self.redis_client.get_active_session(channel_id)
            
            if not conversation:
                return {
                    "is_active": False,
                    "message_count": 0,
                    "participant_count": 0,
                    "duration_minutes": 0
                }
            
            # Calculate duration
            duration_minutes = 0
            if conversation.messages and len(conversation.messages) >= 2:
                start_time = conversation.messages[0].timestamp
                end_time = conversation.messages[-1].timestamp
                duration = end_time - start_time
                duration_minutes = duration.total_seconds() / 60
            
            # Get activity analysis
            activity = await self.conversation_analyzer.analyze_conversation_activity(
                conversation.messages
            )
            
            return {
                "is_active": session is not None,
                "message_count": len(conversation.messages),
                "participant_count": len(conversation.participants),
                "duration_minutes": round(duration_minutes, 1),
                "activity_level": activity.get("activity_level", "inactive"),
                "last_activity": conversation.last_activity,
                "topics": await self.conversation_analyzer.detect_conversation_topics(conversation.messages)
            }
            
        except Exception as e:
            logger.error(f"Failed to get conversation stats: {e}")
            return {"is_active": False, "message_count": 0, "participant_count": 0}
    
    async def cleanup_old_conversations(self, max_age_hours: int = 24):
        """Clean up old conversation data"""
        try:
            # This would be handled by Redis TTL, but we can add manual cleanup if needed
            # For now, just log the cleanup attempt
            logger.info(f"Cleanup requested for conversations older than {max_age_hours} hours")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cleanup old conversations: {e}")
            return False