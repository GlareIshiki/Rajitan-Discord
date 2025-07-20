from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class ScheduleType(str, Enum):
    """Types of schedule execution"""
    PERIODIC = "periodic"
    ONE_TIME = "one_time"


class FunctionType(str, Enum):
    """Types of functions that can be scheduled"""
    SUMMARY = "summary"
    QUIZ = "quiz"
    MUSIC = "music"
    CUSTOM_MESSAGE = "custom_message"


class ExecutionPattern(str, Enum):
    """Execution patterns for periodic schedules"""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ONCE = "once"


class ScheduleStatus(str, Enum):
    """Status of schedule execution"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionTime(BaseModel):
    """Represents when a schedule should execute"""
    pattern: ExecutionPattern
    hour: Optional[int] = None  # 0-23
    minute: Optional[int] = None  # 0-59
    day_of_week: Optional[int] = None  # 0=Monday, 6=Sunday
    day_of_month: Optional[int] = None  # 1-31
    specific_datetime: Optional[datetime] = None
    relative_minutes: Optional[int] = None  # For relative scheduling
    
    def to_next_execution_time(self, base_time: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate next execution time based on pattern"""
        if base_time is None:
            base_time = datetime.now()
        
        if self.pattern == ExecutionPattern.ONCE:
            if self.specific_datetime:
                return self.specific_datetime if self.specific_datetime > base_time else None
            elif self.relative_minutes:
                return base_time + timedelta(minutes=self.relative_minutes)
            else:
                return None
        
        elif self.pattern == ExecutionPattern.HOURLY:
            minute = self.minute or 0
            next_time = base_time.replace(minute=minute, second=0, microsecond=0)
            if next_time <= base_time:
                next_time += timedelta(hours=1)
            return next_time
        
        elif self.pattern == ExecutionPattern.DAILY:
            hour = self.hour or 0
            minute = self.minute or 0
            next_time = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_time <= base_time:
                next_time += timedelta(days=1)
            return next_time
        
        elif self.pattern == ExecutionPattern.WEEKLY:
            hour = self.hour or 0
            minute = self.minute or 0
            target_weekday = self.day_of_week or 0
            
            # Calculate days until target weekday
            current_weekday = base_time.weekday()
            days_ahead = target_weekday - current_weekday
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            
            next_time = base_time + timedelta(days=days_ahead)
            next_time = next_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If today is the target day but time has passed, schedule for next week
            if days_ahead == 7 and next_time <= base_time:
                next_time += timedelta(days=7)
            
            return next_time
        
        elif self.pattern == ExecutionPattern.MONTHLY:
            hour = self.hour or 0
            minute = self.minute or 0
            target_day = self.day_of_month or 1
            
            # Start with this month
            try:
                next_time = base_time.replace(
                    day=target_day, 
                    hour=hour, 
                    minute=minute, 
                    second=0, 
                    microsecond=0
                )
                
                # If time has passed this month, schedule for next month
                if next_time <= base_time:
                    # Move to next month
                    if base_time.month == 12:
                        next_time = next_time.replace(year=base_time.year + 1, month=1)
                    else:
                        next_time = next_time.replace(month=base_time.month + 1)
                
                return next_time
            except ValueError:
                # Day doesn't exist in current month, try next month
                if base_time.month == 12:
                    next_month = base_time.replace(year=base_time.year + 1, month=1, day=1)
                else:
                    next_month = base_time.replace(month=base_time.month + 1, day=1)
                
                try:
                    return next_month.replace(day=target_day, hour=hour, minute=minute)
                except ValueError:
                    return None
        
        return None


class FunctionConfig(BaseModel):
    """Configuration for scheduled function execution"""
    function_type: FunctionType
    custom_message: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ScheduleInfo(BaseModel):
    """Complete schedule information"""
    id: Optional[int] = None
    channel_id: str
    guild_id: str
    schedule_type: ScheduleType
    execution_time: ExecutionTime
    function_config: FunctionConfig
    
    # Management fields
    is_active: bool = True
    created_by: str
    created_at: datetime = Field(default_factory=datetime.now)
    last_executed: Optional[datetime] = None
    next_execution: Optional[datetime] = None
    execution_count: int = 0
    
    # Error handling
    consecutive_failures: int = 0
    max_failures: int = 3
    
    def calculate_next_execution(self, base_time: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate when this schedule should execute next"""
        if not self.is_active:
            return None
        
        if self.schedule_type == ScheduleType.ONE_TIME and self.last_executed:
            return None  # One-time schedules don't repeat
        
        return self.execution_time.to_next_execution_time(base_time)
    
    def mark_executed(self, execution_time: datetime, success: bool = True):
        """Mark schedule as executed"""
        self.last_executed = execution_time
        self.execution_count += 1
        
        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            
        # Disable schedule if too many failures
        if self.consecutive_failures >= self.max_failures:
            self.is_active = False
        
        # Update next execution time
        if self.is_active and self.schedule_type == ScheduleType.PERIODIC:
            self.next_execution = self.calculate_next_execution(execution_time)
        elif self.schedule_type == ScheduleType.ONE_TIME:
            self.is_active = False  # One-time schedules are disabled after execution
    
    def should_execute(self, current_time: datetime) -> bool:
        """Check if schedule should execute at current time"""
        if not self.is_active:
            return False
        
        if self.next_execution is None:
            self.next_execution = self.calculate_next_execution(current_time)
        
        return (self.next_execution is not None and 
                current_time >= self.next_execution)


class ScheduleExecutionResult(BaseModel):
    """Result of a schedule execution"""
    schedule_id: int
    executed_at: datetime
    success: bool
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    output: Optional[str] = None


class ScheduleSummary(BaseModel):
    """Summary information for schedule visualization"""
    id: int
    channel_id: str
    guild_id: str
    function_type: FunctionType
    pattern: ExecutionPattern
    next_execution: Optional[datetime]
    is_active: bool
    execution_count: int
    last_executed: Optional[datetime]
    consecutive_failures: int
    created_by: str
    created_at: datetime
    
    @classmethod
    def from_schedule_info(cls, schedule: ScheduleInfo) -> "ScheduleSummary":
        """Create summary from full schedule info"""
        return cls(
            id=schedule.id or 0,
            channel_id=schedule.channel_id,
            guild_id=schedule.guild_id,
            function_type=schedule.function_config.function_type,
            pattern=schedule.execution_time.pattern,
            next_execution=schedule.next_execution,
            is_active=schedule.is_active,
            execution_count=schedule.execution_count,
            last_executed=schedule.last_executed,
            consecutive_failures=schedule.consecutive_failures,
            created_by=schedule.created_by,
            created_at=schedule.created_at
        )