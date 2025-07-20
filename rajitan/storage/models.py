from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class ConversationState(str, Enum):
    """State of a conversation (inactive, active, cooling down, executing feature)"""
    INACTIVE = "inactive"
    ACTIVE = "active"
    COOLING_DOWN = "cooling"
    FEATURE_EXECUTING = "executing"


class FeatureExecutionState(str, Enum):
    """State of feature execution (idle, preparing, executing, waiting, completed)"""
    IDLE = "idle"
    PREPARING = "preparing"
    EXECUTING = "executing"
    WAITING_RESPONSE = "waiting"
    COMPLETED = "completed"


class Guild(BaseModel):
    """Guild (Discord server) information"""
    id: str
    name: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Channel(BaseModel):
    """Channel information"""
    id: str
    guild_id: str
    name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class Character(BaseModel):
    """Character information"""
    guild_id: str
    name: str
    system_prompt: str
    personality_traits: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Schedule(BaseModel):
    """Scheduled feature execution information"""
    id: Optional[int] = None
    channel_id: str
    guild_id: str
    schedule_type: str  # 'PERIODIC', 'ONE_TIME'
    function_type: str  # 'summary', 'quiz', 'music', 'custom_message'
    custom_message: Optional[str] = None
    
    # Execution pattern
    pattern_type: str  # 'hourly', 'daily', 'weekly', 'monthly', 'once'
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[int] = None  # 0=Monday, 6=Sunday
    day_of_month: Optional[int] = None
    specific_datetime: Optional[datetime] = None
    
    # Management info
    is_active: bool = True
    created_by: str
    created_at: datetime = Field(default_factory=datetime.now)
    last_executed: Optional[datetime] = None
    next_execution: Optional[datetime] = None


class ScheduleExecution(BaseModel):
    """Schedule execution history"""
    id: Optional[int] = None
    schedule_id: int
    executed_at: datetime = Field(default_factory=datetime.now)
    status: str  # 'SUCCESS', 'FAILED', 'SKIPPED'
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None


class UsageStat(BaseModel):
    """Feature usage statistics"""
    id: Optional[int] = None
    guild_id: str
    channel_id: str
    feature_type: str
    execution_time: datetime = Field(default_factory=datetime.now)
    success: bool = True


class Message(BaseModel):
    """Message information"""
    user_id: str
    username: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class Conversation(BaseModel):
    """Conversation data for a channel"""
    channel_id: str
    messages: List[Message] = Field(default_factory=list)
    last_activity: datetime = Field(default_factory=datetime.now)
    message_count: int = 0
    participants: List[str] = Field(default_factory=list)
    state: ConversationState = ConversationState.INACTIVE


class ActiveSession(BaseModel):
    """Active session information for a channel"""
    channel_id: str
    last_activity: datetime = Field(default_factory=datetime.now)
    message_count: int = 0
    participants: List[str] = Field(default_factory=list)


class FeatureHistory(BaseModel):
    """Feature execution history for a channel"""
    channel_id: str
    feature: str
    last_executed: datetime = Field(default_factory=datetime.now)
    execution_count: int = 0


class Quiz(BaseModel):
    """Quiz data for a channel"""
    questions: List[Dict[str, Any]]
    channel_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    current_question: int = 0
    participants: Dict[str, int] = Field(default_factory=dict)  # user_id: score
    is_active: bool = True


class MusicRecommendation(BaseModel):
    """Music recommendation data"""
    title: str
    artist: str
    url: str
    reason: str
    channel_id: str
    created_at: datetime = Field(default_factory=datetime.now)


class SummaryData(BaseModel):
    """Summary data for a channel"""
    channel_id: str
    content: str
    message_count: int
    participants: List[str]
    created_at: datetime = Field(default_factory=datetime.now)