import asyncio
import redis.asyncio as redis
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from rajitan.storage.models import Conversation, Message, ActiveSession, FeatureHistory
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config
from rajitan.utils.decorators import handle_async_errors

logger = get_logger("redis_client")
config = get_config()


class RedisClient:
    """Redis client for caching and session management"""
    
    def __init__(self):
        self.redis_pool = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize Redis connection"""
        if self._initialized:
            return
        
        try:
            self.redis_pool = redis.ConnectionPool(
                host=config.redis_host,
                port=config.redis_port,
                password=config.redis_password,
                db=config.redis_db,
                decode_responses=True,
                retry_on_timeout=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # Test connection
            async with redis.Redis(connection_pool=self.redis_pool) as r:
                await r.ping()
            
            self._initialized = True
            logger.info("Redis client initialized successfully")
        except Exception as e:
            logger.warning(f"Redis not available, using in-memory cache: {e}")
            # Fall back to in-memory cache if Redis is not available
            self._use_fallback = True
            self._memory_cache = {}
            self._initialized = True  # Mark as initialized to prevent retry loops
    
    async def _get_redis(self):
        """Get Redis connection"""
        if not self._initialized:
            await self.initialize()
        
        if hasattr(self, '_use_fallback') and self._use_fallback:
            return None
        
        try:
            return redis.Redis(connection_pool=self.redis_pool)
        except Exception as e:
            logger.warning(f"Failed to get Redis connection: {e}")
            return None
    
    # Conversation operations
    @handle_async_errors(operation_name="store conversation", default_return=False)
    async def store_conversation(self, conversation: Conversation, ttl: int = 86400):
        """Store conversation data (TTL: 24 hours)"""
        r = await self._get_redis()
        if r is None:
            # Fallback to memory cache
            self._memory_cache[f"conversation:{conversation.channel_id}"] = conversation.dict()
            return True
        
        async with r:
            key = f"conversation:{conversation.channel_id}"
            data = conversation.dict()
            # Convert datetime objects to ISO format
            data['last_activity'] = data['last_activity'].isoformat()
            for msg in data['messages']:
                msg['timestamp'] = msg['timestamp'].isoformat()
            
            await r.setex(key, ttl, json.dumps(data))
            return True
    
    @handle_async_errors(operation_name="get conversation", default_return=None)
    async def get_conversation(self, channel_id: str) -> Optional[Conversation]:
        """Get conversation data"""
        r = await self._get_redis()
        if r is None:
            # Fallback to memory cache
            data = self._memory_cache.get(f"conversation:{channel_id}")
            if data:
                return Conversation(**data)
            return None
        
        async with r:
            key = f"conversation:{channel_id}"
            data = await r.get(key)
            if data:
                data = json.loads(data)
                # Convert ISO format back to datetime
                data['last_activity'] = datetime.fromisoformat(data['last_activity'])
                for msg in data['messages']:
                    msg['timestamp'] = datetime.fromisoformat(msg['timestamp'])
                return Conversation(**data)
            return None
    
    @handle_async_errors(operation_name="add message to conversation", default_return=False)
    async def add_message_to_conversation(self, channel_id: str, message: Message):
        """Add message to conversation"""
        conversation = await self.get_conversation(channel_id)
        if conversation is None:
            conversation = Conversation(
                channel_id=channel_id,
                messages=[],
                last_activity=datetime.now(),
                message_count=0,
                participants=[]
            )
        
        conversation.messages.append(message)
        conversation.last_activity = datetime.now()
        conversation.message_count += 1
        
        if message.user_id not in conversation.participants:
            conversation.participants.append(message.user_id)
        
        # Keep only last 100 messages
        if len(conversation.messages) > 100:
            conversation.messages = conversation.messages[-100:]
        
        await self.store_conversation(conversation)
        return True
    
    async def get_recent_messages(self, channel_id: str, minutes: int = 60) -> List[Message]:
        """Get recent messages from conversation"""
        try:
            conversation = await self.get_conversation(channel_id)
            if not conversation:
                return []
            
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            recent_messages = [
                msg for msg in conversation.messages
                if msg.timestamp >= cutoff_time
            ]
            
            return recent_messages
        except Exception as e:
            logger.error(f"Failed to get recent messages: {e}")
            return []
    
    # Active session operations
    @handle_async_errors(operation_name="store active session", default_return=False)
    async def store_active_session(self, session: ActiveSession, ttl: int = 3600):
        """Store active session (TTL: 1 hour)"""
        r = await self._get_redis()
        if r is None:
            # Fallback to memory cache
            self._memory_cache[f"session:{session.channel_id}"] = session.dict()
            return True
        
        async with r:
            key = f"session:{session.channel_id}"
            data = session.dict()
            data['last_activity'] = data['last_activity'].isoformat()
            
            await r.setex(key, ttl, json.dumps(data))
            return True
    
    @handle_async_errors(operation_name="get active session", default_return=None)
    async def get_active_session(self, channel_id: str) -> Optional[ActiveSession]:
        """Get active session"""
        r = await self._get_redis()
        if r is None:
            # Fallback to memory cache
            data = self._memory_cache.get(f"session:{channel_id}")
            if data:
                return ActiveSession(**data)
            return None
        
        async with r:
            key = f"session:{channel_id}"
            data = await r.get(key)
            if data:
                data = json.loads(data)
                data['last_activity'] = datetime.fromisoformat(data['last_activity'])
                return ActiveSession(**data)
            return None
    
    async def is_conversation_active(self, channel_id: str, timeout_minutes: int = 30) -> bool:
        """Check if conversation is active"""
        try:
            session = await self.get_active_session(channel_id)
            if not session:
                return False
            
            timeout = datetime.now() - timedelta(minutes=timeout_minutes)
            return session.last_activity >= timeout
        except Exception as e:
            logger.error(f"Failed to check conversation activity: {e}")
            return False
    
    # Feature history operations
    async def store_feature_history(self, history: FeatureHistory, ttl: int = 604800):
        """Store feature execution history (TTL: 7 days)"""
        try:
            r = await self._get_redis()
            if r is None:
                # Fallback to memory cache
                self._memory_cache[f"feature_history:{history.channel_id}:{history.feature}"] = history.dict()
                return True
            
            async with r:
                key = f"feature_history:{history.channel_id}:{history.feature}"
                data = history.dict()
                data['last_executed'] = data['last_executed'].isoformat()
                
                await r.setex(key, ttl, json.dumps(data))
                return True
        except Exception as e:
            logger.error(f"Failed to store feature history: {e}")
            return False
    
    async def get_feature_history(self, channel_id: str, feature: str) -> Optional[FeatureHistory]:
        """Get feature execution history"""
        try:
            r = await self._get_redis()
            if r is None:
                # Fallback to memory cache
                data = self._memory_cache.get(f"feature_history:{channel_id}:{feature}")
                if data:
                    return FeatureHistory(**data)
                return None
            
            async with r:
                key = f"feature_history:{channel_id}:{feature}"
                data = await r.get(key)
                if data:
                    data = json.loads(data)
                    data['last_executed'] = datetime.fromisoformat(data['last_executed'])
                    return FeatureHistory(**data)
                return None
        except Exception as e:
            logger.error(f"Failed to get feature history: {e}")
            return None
    
    async def can_execute_feature(self, channel_id: str, feature: str, interval_minutes: int) -> bool:
        """Check if feature can be executed based on interval"""
        try:
            history = await self.get_feature_history(channel_id, feature)
            if not history:
                return True
            
            interval = datetime.now() - timedelta(minutes=interval_minutes)
            return history.last_executed <= interval
        except Exception as e:
            logger.error(f"Failed to check feature execution: {e}")
            return True
    
    # Generic cache operations
    @handle_async_errors(operation_name="set cache", default_return=False)
    async def set_cache(self, key: str, value: Any, ttl: int = 3600):
        """Set cache value"""
        r = await self._get_redis()
        if r is None:
            # Fallback to memory cache
            self._memory_cache[key] = value
            return True
        
        async with r:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            await r.setex(key, ttl, value)
            return True
    
    @handle_async_errors(operation_name="get cache", default_return=None)
    async def get_cache(self, key: str) -> Any:
        """Get cache value"""
        r = await self._get_redis()
        if r is None:
            # Fallback to memory cache
            return self._memory_cache.get(key)
        
        async with r:
            value = await r.get(key)
            if value:
                try:
                    return json.loads(value)
                except:
                    return value
            return None
    
    async def delete_cache(self, key: str):
        """Delete cache value"""
        try:
            r = await self._get_redis()
            if r is None:
                # Fallback to memory cache
                if key in self._memory_cache:
                    del self._memory_cache[key]
                return True
            
            async with r:
                await r.delete(key)
                return True
        except Exception as e:
            logger.error(f"Failed to delete cache: {e}")
            return False
    
    async def close(self):
        """Close Redis connection"""
        if self.redis_pool:
            await self.redis_pool.disconnect()