import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import Counter
from rajitan.storage.models import Message, ConversationState
from rajitan.api.openai_client import OpenAIClient
from rajitan.utils.logger import get_logger

logger = get_logger("conversation_analyzer")


class ConversationAnalyzer:
    """Analyzes conversation patterns and determines appropriate actions"""
    
    def __init__(self, openai_client: OpenAIClient):
        self.openai_client = openai_client
    
    async def analyze_conversation_activity(
        self, 
        messages: List[Message], 
        time_window_minutes: int = 30
    ) -> Dict[str, Any]:
        """Analyze conversation activity patterns"""
        try:
            if not messages:
                return {
                    "is_active": False,
                    "message_count": 0,
                    "participant_count": 0,
                    "activity_level": "inactive"
                }
            
            # Filter messages within time window
            cutoff_time = datetime.now() - timedelta(minutes=time_window_minutes)
            recent_messages = [msg for msg in messages if msg.timestamp >= cutoff_time]
            
            if not recent_messages:
                return {
                    "is_active": False,
                    "message_count": len(messages),
                    "participant_count": len(set(msg.user_id for msg in messages)),
                    "activity_level": "inactive"
                }
            
            # Calculate metrics
            message_count = len(recent_messages)
            participants = set(msg.user_id for msg in recent_messages)
            participant_count = len(participants)
            
            # Calculate activity level
            activity_level = self._calculate_activity_level(message_count, participant_count, time_window_minutes)
            
            # Calculate message frequency (messages per minute)
            message_frequency = message_count / time_window_minutes
            
            # Find most active participants
            user_message_counts = Counter(msg.user_id for msg in recent_messages)
            most_active = user_message_counts.most_common(3)
            
            return {
                "is_active": message_count > 0,
                "message_count": message_count,
                "participant_count": participant_count,
                "activity_level": activity_level,
                "message_frequency": message_frequency,
                "most_active_users": [{"user_id": user_id, "count": count} for user_id, count in most_active],
                "time_window": time_window_minutes
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze conversation activity: {e}")
            return {"is_active": False, "message_count": 0, "participant_count": 0}
    
    def _calculate_activity_level(self, message_count: int, participant_count: int, time_window: int) -> str:
        """Calculate activity level based on message count and participants"""
        messages_per_minute = message_count / time_window
        
        if messages_per_minute >= 2.0 and participant_count >= 3:
            return "very_high"
        elif messages_per_minute >= 1.0 and participant_count >= 2:
            return "high"
        elif messages_per_minute >= 0.5:
            return "medium"
        elif messages_per_minute >= 0.1:
            return "low"
        else:
            return "inactive"
    
    async def detect_conversation_topics(self, messages: List[Message]) -> List[str]:
        """Detect main topics in conversation"""
        try:
            if not messages:
                return []
            
            # Simple keyword-based topic detection
            text_content = " ".join([msg.content for msg in messages[-20:]])  # Last 20 messages
            
            # Common topic keywords (can be expanded)
            topic_keywords = {
                "ゲーム": ["ゲーム", "ゲーミング", "プレイ", "ゲームアプリ", "ビデオゲーム", "RPG", "FPS", "シューティング"],
                "プログラミング": ["プログラマー", "コード", "プログラム", "API", "アプリ開発", "プログラミング言語", "コーディング"],
                "アニメ": ["アニメ", "マンガ", "アニメキャラ", "アニメ作品", "OP", "ED", "アニメソング"],
                "音楽": ["音楽", "楽曲", "アーティスト", "アーティスト名", "歌手", "バンド", "コンサート"],
                "映画": ["映画", "映画鑑賞", "映画作品", "映画館", "シネマ", "ムビー", "映像"],
                "テレビ": ["テレビ", "ドラマ", "テレビ番組", "バラエティ", "ニュース", "放送", "Netflix"],
                "スポーツ": ["スポーツ", "運動", "サッカー", "野球", "バスケ", "競技", "オリンピック"],
                "料理": ["料理", "料理作り", "食べ物", "飲食", "食事", "グルメ", "レシピ"]
            }
            
            detected_topics = []
            for topic, keywords in topic_keywords.items():
                if any(keyword in text_content for keyword in keywords):
                    detected_topics.append(topic)
            
            return detected_topics[:3]  # Return top 3 topics
            
        except Exception as e:
            logger.error(f"Failed to detect conversation topics: {e}")
            return []
    
    async def analyze_sentiment(self, messages: List[Message]) -> Optional[str]:
        """Analyze overall conversation sentiment"""
        try:
            if not messages:
                return None
            
            # Use OpenAI for sentiment analysis
            sentiment = await self.openai_client.analyze_conversation_sentiment(messages)
            return sentiment
            
        except Exception as e:
            logger.error(f"Failed to analyze sentiment: {e}")
            return None
    
    async def detect_conversation_end(
        self, 
        messages: List[Message], 
        inactivity_threshold_minutes: int = 15
    ) -> bool:
        """Detect if conversation has naturally ended"""
        try:
            if not messages:
                return True
            
            # Check if last message is older than threshold
            last_message_time = messages[-1].timestamp
            threshold_time = datetime.now() - timedelta(minutes=inactivity_threshold_minutes)
            
            if last_message_time < threshold_time:
                return True
            
            # Check for conversation ending patterns
            recent_messages = messages[-5:]  # Last 5 messages
            ending_patterns = [
                "おつかれ", "おつかれさま", "また明日", "おやすみ", "失礼", "また明日ね",
                "さよなら", "さようなら", "終了", "bye", "see you", "good night"
            ]
            
            for msg in recent_messages:
                if any(pattern in msg.content.lower() for pattern in ending_patterns):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to detect conversation end: {e}")
            return False
    
    async def should_intervene(
        self, 
        messages: List[Message], 
        feature_type: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """Determine if bot should intervene with a specific feature"""
        try:
            if not messages:
                return False
            
            context = context or {}
            
            # Analyze current activity
            activity = await self.analyze_conversation_activity(messages)
            
            if feature_type == "summary":
                # Summarize when conversation is winding down or has many messages
                message_count = len(messages)
                activity_level = activity.get("activity_level", "inactive")
                
                # Don't summarize if conversation is very active
                if activity_level in ["very_high", "high"]:
                    return False
                
                # Summarize if many messages or conversation seems to be ending
                if message_count >= 30 or activity_level == "low":
                    return True
                
                return False
            
            elif feature_type == "quiz":
                # Quiz when conversation is active and positive
                activity_level = activity.get("activity_level", "inactive")
                participant_count = activity.get("participant_count", 0)
                
                # Need active conversation with multiple participants
                if activity_level not in ["medium", "high"] or participant_count < 2:
                    return False
                
                # Check sentiment
                sentiment = context.get("sentiment")
                if sentiment in ["positive", "excited"]:
                    return True
                
                return False
            
            elif feature_type == "music":
                # Music recommendation based on mood and activity
                activity_level = activity.get("activity_level", "inactive")
                
                # Can recommend music at various activity levels
                if activity_level in ["inactive"]:
                    return False
                
                # Check if music topic was mentioned
                topics = await self.detect_conversation_topics(messages)
                if "音楽" in topics:
                    return True
                
                # Random chance based on sentiment
                sentiment = context.get("sentiment", "neutral")
                if sentiment != "neutral":
                    return True
                
                return False
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to determine intervention: {e}")
            return False
    
    async def get_conversation_context(self, messages: List[Message]) -> Dict[str, Any]:
        """Get comprehensive conversation context for decision making"""
        try:
            activity = await self.analyze_conversation_activity(messages)
            topics = await self.detect_conversation_topics(messages)
            sentiment = await self.analyze_sentiment(messages)
            is_ending = await self.detect_conversation_end(messages)
            
            return {
                "activity": activity,
                "topics": topics,
                "sentiment": sentiment,
                "is_ending": is_ending,
                "message_count": len(messages),
                "participant_count": len(set(msg.user_id for msg in messages)) if messages else 0,
                "last_message_time": messages[-1].timestamp if messages else None
            }
            
        except Exception as e:
            logger.error(f"Failed to get conversation context: {e}")
            return {"activity": {"is_active": False}, "topics": [], "sentiment": None}