import asyncio
import json
import aiosqlite
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from rajitan.scheduler.schedule_models import (
    ScheduleInfo, ExecutionTime, FunctionConfig, 
    ScheduleType, FunctionType, ExecutionPattern,
    ScheduleExecutionResult, ScheduleSummary
)
from rajitan.storage.models import Schedule, ScheduleExecution
from rajitan.storage.sqlite_client import SQLiteClient
from rajitan.utils.logger import get_logger
from rajitan.utils.decorators import handle_async_errors

logger = get_logger("enhanced_schedule_manager")


class EnhancedScheduleManager:
    """Enhanced schedule manager with support for periodic and one-time schedules"""
    
    def __init__(self, db_client: SQLiteClient, bot=None):
        self.db_client = db_client
        self.bot = bot
        self._running = False
        self._check_interval = 60  # Check every minute
        self._check_task = None
    
    async def start(self):
        """Start the schedule manager"""
        if self._running:
            return
        
        self._running = True
        self._check_task = asyncio.create_task(self._schedule_check_loop())
        logger.info("Enhanced schedule manager started")
    
    async def stop(self):
        """Stop the schedule manager"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Enhanced schedule manager stopped")
    
    @handle_async_errors(operation_name="create schedule", default_return=False)
    async def create_schedule(self, schedule_info: ScheduleInfo) -> bool:
        """Create a new schedule"""
        # Calculate next execution time
        schedule_info.next_execution = schedule_info.calculate_next_execution()
        
        # Convert to database model
        schedule_db = self._schedule_info_to_db_model(schedule_info)
        
        # Save to database
        success = await self._save_schedule_to_db(schedule_db)
        if success:
            logger.info(f"Created schedule: {schedule_info.function_config.function_type} "
                       f"for channel {schedule_info.channel_id}")
        
        return success
    
    @handle_async_errors(operation_name="get channel schedules", default_return=[])
    async def get_channel_schedules(self, channel_id: str) -> List[ScheduleSummary]:
        """Get all schedules for a channel"""
        schedules = await self.db_client.get_schedules(channel_id)
        summaries = []
        
        for schedule in schedules:
            schedule_info = self._db_model_to_schedule_info(schedule)
            summary = ScheduleSummary.from_schedule_info(schedule_info)
            summaries.append(summary)
        
        return summaries
    
    async def get_guild_schedules(self, guild_id: str) -> List[ScheduleSummary]:
        """Get all schedules for a guild"""
        try:
            schedules = await self._get_guild_schedules_from_db(guild_id)
            summaries = []
            
            for schedule in schedules:
                schedule_info = self._db_model_to_schedule_info(schedule)
                summary = ScheduleSummary.from_schedule_info(schedule_info)
                summaries.append(summary)
            
            return summaries
            
        except Exception as e:
            logger.error(f"Failed to get guild schedules: {e}")
            return []
    
    async def delete_schedule(self, schedule_id: int) -> bool:
        """Delete a schedule"""
        try:
            success = await self._delete_schedule_from_db(schedule_id)
            if success:
                logger.info(f"Deleted schedule {schedule_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to delete schedule: {e}")
            return False
    
    async def toggle_schedule(self, schedule_id: int) -> bool:
        """Toggle schedule active status"""
        try:
            success = await self._toggle_schedule_in_db(schedule_id)
            if success:
                logger.info(f"Toggled schedule {schedule_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to toggle schedule: {e}")
            return False
    
    async def _schedule_check_loop(self):
        """Main loop for checking and executing schedules"""
        while self._running:
            try:
                await self._check_and_execute_schedules()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in schedule check loop: {e}")
                await asyncio.sleep(self._check_interval)
    
    async def _check_and_execute_schedules(self):
        """Check for schedules that need to be executed"""
        try:
            current_time = datetime.now()
            executable_schedules = await self._get_executable_schedules(current_time)
            
            logger.debug(f"Checking schedules at {current_time}, found {len(executable_schedules)} executable schedules")
            
            for schedule in executable_schedules:
                try:
                    logger.info(f"Executing schedule {schedule.id}: {schedule.function_config.function_type} for channel {schedule.channel_id}")
                    await self._execute_schedule(schedule, current_time)
                except Exception as e:
                    logger.error(f"Failed to execute schedule {schedule.id}: {e}")
                    await self._record_execution_failure(schedule.id or 0, str(e))
            
        except Exception as e:
            logger.error(f"Error checking schedules: {e}")
    
    async def _execute_schedule(self, schedule: ScheduleInfo, execution_time: datetime):
        """Execute a specific schedule"""
        start_time = datetime.now()
        
        try:
            # Execute the scheduled function
            success = await self._execute_scheduled_function(schedule)
            
            # Calculate execution time
            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # Record execution result
            result = ScheduleExecutionResult(
                schedule_id=schedule.id or 0,
                executed_at=execution_time,
                success=success,
                execution_time_ms=execution_time_ms
            )
            
            await self._record_execution_result(result)
            
            # Update schedule
            schedule.mark_executed(execution_time, success)
            await self._update_schedule_after_execution(schedule)
            
        except Exception as e:
            logger.error(f"Error executing schedule {schedule.id}: {e}")
            raise
    
    async def _execute_scheduled_function(self, schedule: ScheduleInfo) -> bool:
        """Execute the actual scheduled function"""
        try:
            function_type = schedule.function_config.function_type
            
            if function_type == FunctionType.SUMMARY:
                return await self._execute_summary_function(schedule)
            elif function_type == FunctionType.QUIZ:
                return await self._execute_quiz_function(schedule)
            elif function_type == FunctionType.MUSIC:
                return await self._execute_music_function(schedule)
            elif function_type == FunctionType.CUSTOM_MESSAGE:
                return await self._execute_custom_message_function(schedule)
            else:
                logger.error(f"Unknown function type: {function_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing function: {e}")
            return False
    
    @handle_async_errors(operation_name="execute summary function", default_return=False)
    async def _execute_summary_function(self, schedule: ScheduleInfo) -> bool:
        """Execute summary function"""
        if not self.bot:
            logger.error("Bot instance not available for schedule execution")
            return False
        
        channel = self.bot.get_channel(int(schedule.channel_id))
        if not channel:
            logger.error(f"Channel {schedule.channel_id} not found")
            return False
        
        # Get conversation data
        summary_data = await self.bot.conversation_tracker.get_conversation_summary_data(schedule.channel_id)
        
        if not summary_data or not summary_data.get("messages"):
            logger.info(f"No conversation data for summary in channel {schedule.channel_id}")
            return True  # Consider this successful - just nothing to summarize
        
        # Generate summary
        summary = await self.bot.conversation_summarizer.generate_summary(
            guild_id=schedule.guild_id,
            channel_id=schedule.channel_id,
            messages=summary_data["messages"]
        )
        
        if summary:
            formatted_summary = await self.bot.conversation_summarizer.format_summary_for_discord(summary)
            intro_message = "📅 定期要約のお時間です♪\n\n"
            full_response = intro_message + formatted_summary
            
            await channel.send(full_response)
            logger.info(f"Summary successfully executed for channel {schedule.channel_id}")
            return True
        else:
            logger.error("Failed to generate summary")
            return False
    
    async def _execute_quiz_function(self, schedule: ScheduleInfo) -> bool:
        """Execute quiz function"""
        try:
            if not self.bot:
                logger.error("Bot instance not available for schedule execution")
                return False
            
            channel = self.bot.get_channel(int(schedule.channel_id))
            if not channel:
                logger.error(f"Channel {schedule.channel_id} not found")
                return False
            
            # Check if quiz is already active
            if await self.bot.quiz_runner.is_quiz_active(schedule.channel_id):
                logger.info(f"Quiz already active in channel {schedule.channel_id}")
                return True
            
            # Get conversation data
            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                schedule.channel_id, duration_minutes=60
            )

            # Fallback to Discord channel history if insufficient tracked data
            if len(recent_messages) < 5:
                recent_messages = await self.bot.fetch_discord_history_as_messages(
                    channel, limit=50
                )

            if len(recent_messages) < 5:
                logger.info(f"Not enough conversation data for quiz in channel {schedule.channel_id}")
                await channel.send("📅 定期クイズのお時間ですが、会話データが不足しているため、今回はスキップします。")
                return True
            
            # Generate and start quiz
            quiz = await self.bot.quiz_generator.generate_quiz(
                guild_id=schedule.guild_id,
                channel_id=schedule.channel_id,
                messages=recent_messages
            )
            
            if quiz and await self.bot.quiz_runner.start_quiz(schedule.channel_id, quiz):
                question_info = await self.bot.quiz_runner.get_current_question(schedule.channel_id)
                if question_info:
                    question_text = self.bot.quiz_generator.format_question_for_discord(
                        question_info["question"],
                        question_info["question_number"],
                        question_info["total_questions"]
                    )
                    await channel.send(f"📅 定期クイズのお時間です♪\n\n{question_text}")
                    logger.info(f"Quiz successfully executed for channel {schedule.channel_id}")
                    return True
                else:
                    logger.error("Failed to get quiz question")
                    return False
            else:
                logger.error("Failed to generate or start quiz")
                return False
                
        except Exception as e:
            logger.error(f"Error executing quiz function: {e}")
            return False
    
    async def _execute_music_function(self, schedule: ScheduleInfo) -> bool:
        """Execute music recommendation function"""
        try:
            if not self.bot:
                logger.error("Bot instance not available for schedule execution")
                return False

            channel = self.bot.get_channel(int(schedule.channel_id))
            if not channel:
                logger.error(f"Channel {schedule.channel_id} not found")
                return False

            # Get recent conversation for mood analysis
            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                schedule.channel_id, duration_minutes=30
            )

            # Fallback to Discord channel history if no tracked data
            if not recent_messages:
                recent_messages = await self.bot.fetch_discord_history_as_messages(
                    channel, limit=30
                )

            if not recent_messages:
                await channel.send("📅 定期音楽推薦のお時間です♪\n\n現在の雰囲気に合った音楽をおすすめしたいのですが、最近の会話が見つからないため、今回はスキップします。")
                return True

            # Check if music recommender is available
            if not self.bot.music_recommender:
                logger.warning("Music recommender not available, using fallback message")
                await channel.send("📅 定期音楽推薦のお時間です♪\n\n（音楽推薦機能の設定が必要です）")
                return True

            # Generate music recommendation
            recommendation = await self.bot.music_recommender.generate_recommendation(
                guild_id=schedule.guild_id,
                channel_id=schedule.channel_id,
                messages=recent_messages
            )

            if recommendation:
                formatted = self.bot.music_recommender.format_recommendation_for_discord(recommendation)
                intro = "📅 定期音楽推薦のお時間です♪\n\n"
                await channel.send(intro + formatted)
                logger.info(f"Music recommendation executed for channel {schedule.channel_id}")
                return True
            else:
                await channel.send("📅 定期音楽推薦のお時間です♪\n\n今の雰囲気にぴったりの曲が見つからなかったみたい。また次回ね！")
                return True

        except Exception as e:
            logger.error(f"Error executing music function: {e}")
            return False
    
    async def _execute_custom_message_function(self, schedule: ScheduleInfo) -> bool:
        """Execute custom message function"""
        try:
            if not self.bot:
                logger.error("Bot instance not available for schedule execution")
                return False
            
            channel = self.bot.get_channel(int(schedule.channel_id))
            if not channel:
                logger.error(f"Channel {schedule.channel_id} not found")
                return False
            
            message = schedule.function_config.custom_message or "📅 定期メッセージです。"
            await channel.send(message)
            
            logger.info(f"Custom message executed for channel {schedule.channel_id}: {message}")
            return True
                
        except Exception as e:
            logger.error(f"Error executing custom message function: {e}")
            return False
    
    def _schedule_info_to_db_model(self, schedule_info: ScheduleInfo) -> Schedule:
        """Convert ScheduleInfo to database model"""
        return Schedule(
            id=schedule_info.id,
            channel_id=schedule_info.channel_id,
            guild_id=schedule_info.guild_id,
            schedule_type=schedule_info.schedule_type.value,
            function_type=schedule_info.function_config.function_type.value,
            custom_message=schedule_info.function_config.custom_message,
            pattern_type=schedule_info.execution_time.pattern.value,
            hour=schedule_info.execution_time.hour,
            minute=schedule_info.execution_time.minute,
            day_of_week=schedule_info.execution_time.day_of_week,
            day_of_month=schedule_info.execution_time.day_of_month,
            specific_datetime=schedule_info.execution_time.specific_datetime,
            is_active=schedule_info.is_active,
            created_by=schedule_info.created_by,
            created_at=schedule_info.created_at,
            last_executed=schedule_info.last_executed,
            next_execution=schedule_info.next_execution
        )
    
    def _db_model_to_schedule_info(self, schedule: Schedule) -> ScheduleInfo:
        """Convert database model to ScheduleInfo"""
        execution_time = ExecutionTime(
            pattern=ExecutionPattern(schedule.pattern_type),
            hour=schedule.hour,
            minute=schedule.minute,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
            specific_datetime=schedule.specific_datetime
        )
        
        function_config = FunctionConfig(
            function_type=FunctionType(schedule.function_type),
            custom_message=schedule.custom_message,
            parameters={}
        )
        
        return ScheduleInfo(
            id=schedule.id,
            channel_id=schedule.channel_id,
            guild_id=schedule.guild_id,
            schedule_type=ScheduleType(schedule.schedule_type),
            execution_time=execution_time,
            function_config=function_config,
            is_active=schedule.is_active,
            created_by=schedule.created_by,
            created_at=schedule.created_at,
            last_executed=schedule.last_executed,
            next_execution=schedule.next_execution
        )
    
    @handle_async_errors(operation_name="save schedule to database", default_return=False)
    async def _save_schedule_to_db(self, schedule: Schedule) -> bool:
        """Save schedule to database"""
        async with aiosqlite.connect(self.db_client.db_path) as db:
            await db.execute('''
                INSERT INTO schedules (
                    channel_id, guild_id, schedule_type, function_type, custom_message,
                    pattern_type, hour, minute, day_of_week, day_of_month, specific_datetime,
                    is_active, created_by, created_at, last_executed, next_execution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                schedule.channel_id, schedule.guild_id, schedule.schedule_type, 
                schedule.function_type, schedule.custom_message,
                schedule.pattern_type, schedule.hour, schedule.minute, 
                schedule.day_of_week, schedule.day_of_month, schedule.specific_datetime,
                schedule.is_active, schedule.created_by, schedule.created_at,
                schedule.last_executed, schedule.next_execution
            ))
            await db.commit()
            return True
    
    async def _get_executable_schedules(self, current_time: datetime) -> List[ScheduleInfo]:
        """Get schedules that should be executed at current time"""
        try:
            async with aiosqlite.connect(self.db_client.db_path) as db:
                # First, get all active schedules for debugging
                async with db.execute('SELECT COUNT(*) FROM schedules WHERE is_active = TRUE') as cursor:
                    total_active = (await cursor.fetchone())[0]
                    logger.debug(f"Total active schedules in database: {total_active}")
                
                async with db.execute('''
                    SELECT * FROM schedules 
                    WHERE is_active = TRUE 
                    AND (next_execution IS NULL OR next_execution <= ?)
                ''', (current_time,)) as cursor:
                    rows = await cursor.fetchall()
                    logger.debug(f"Found {len(rows)} schedules due for execution at {current_time}")
                    
                    schedules = []
                    for row in rows:
                        schedule = self._row_to_schedule(row)
                        schedule_info = self._db_model_to_schedule_info(schedule)
                        
                        logger.debug(f"Checking schedule {schedule_info.id}: next_execution={schedule_info.next_execution}")
                        
                        if schedule_info.should_execute(current_time):
                            logger.debug(f"Schedule {schedule_info.id} should execute")
                            schedules.append(schedule_info)
                        else:
                            logger.debug(f"Schedule {schedule_info.id} should not execute yet")
                    
                    return schedules
        except Exception as e:
            logger.error(f"Failed to get executable schedules: {e}")
            return []
    
    async def _record_execution_result(self, result: ScheduleExecutionResult):
        """Record schedule execution result"""
        try:
            execution = ScheduleExecution(
                schedule_id=result.schedule_id,
                executed_at=result.executed_at,
                status="SUCCESS" if result.success else "FAILED",
                error_message=result.error_message,
                execution_time_ms=result.execution_time_ms
            )
            
            async with aiosqlite.connect(self.db_client.db_path) as db:
                await db.execute('''
                    INSERT INTO schedule_executions (
                        schedule_id, executed_at, status, error_message, execution_time_ms
                    ) VALUES (?, ?, ?, ?, ?)
                ''', (
                    execution.schedule_id, execution.executed_at, execution.status,
                    execution.error_message, execution.execution_time_ms
                ))
                await db.commit()
                
        except Exception as e:
            logger.error(f"Failed to record execution result: {e}")
    
    async def _record_execution_failure(self, schedule_id: int, error_message: str):
        """Record schedule execution failure"""
        result = ScheduleExecutionResult(
            schedule_id=schedule_id,
            executed_at=datetime.now(),
            success=False,
            error_message=error_message
        )
        await self._record_execution_result(result)
    
    async def _update_schedule_after_execution(self, schedule: ScheduleInfo):
        """Update schedule in database after execution"""
        try:
            async with aiosqlite.connect(self.db_client.db_path) as db:
                await db.execute('''
                    UPDATE schedules 
                    SET last_executed = ?, next_execution = ?, is_active = ?
                    WHERE id = ?
                ''', (
                    schedule.last_executed, schedule.next_execution, 
                    schedule.is_active, schedule.id
                ))
                await db.commit()
                
        except Exception as e:
            logger.error(f"Failed to update schedule after execution: {e}")
    
    def _row_to_schedule(self, row) -> Schedule:
        """Convert database row to Schedule model"""
        return Schedule(
            id=row[0], channel_id=row[1], guild_id=row[2], schedule_type=row[3],
            function_type=row[4], custom_message=row[5], pattern_type=row[6],
            hour=row[7], minute=row[8], day_of_week=row[9], day_of_month=row[10],
            specific_datetime=datetime.fromisoformat(row[11]) if row[11] else None,
            is_active=bool(row[12]), created_by=row[13],
            created_at=datetime.fromisoformat(row[14]),
            last_executed=datetime.fromisoformat(row[15]) if row[15] else None,
            next_execution=datetime.fromisoformat(row[16]) if row[16] else None
        )
    
    async def _get_guild_schedules_from_db(self, guild_id: str) -> List[Schedule]:
        """Get all schedules for a guild from database"""
        try:
            async with aiosqlite.connect(self.db_client.db_path) as db:
                async with db.execute(
                    'SELECT * FROM schedules WHERE guild_id = ? ORDER BY created_at DESC',
                    (guild_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [self._row_to_schedule(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get guild schedules: {e}")
            return []
    
    async def _delete_schedule_from_db(self, schedule_id: int) -> bool:
        """Delete schedule from database"""
        try:
            async with aiosqlite.connect(self.db_client.db_path) as db:
                await db.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete schedule: {e}")
            return False
    
    async def _toggle_schedule_in_db(self, schedule_id: int) -> bool:
        """Toggle schedule active status in database"""
        try:
            async with aiosqlite.connect(self.db_client.db_path) as db:
                await db.execute(
                    'UPDATE schedules SET is_active = NOT is_active WHERE id = ?',
                    (schedule_id,)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to toggle schedule: {e}")
            return False