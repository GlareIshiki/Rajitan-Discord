"""
Trigger Manager for automatic feature execution.

Monitors conversations and triggers features (summary, quiz, music) based on
conversation state and configurable conditions.
"""

import asyncio
from typing import Dict, Any, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from rajitan.utils.logger import get_logger
from rajitan.features.levemagi_notifier import LeveMagiNotifier

logger = get_logger("trigger_manager")


class TriggerType(Enum):
    """Types of triggers"""
    SUMMARY = "summary"
    QUIZ = "quiz"
    MUSIC = "music"


@dataclass
class TriggerCondition:
    """Conditions for triggering a feature"""
    min_messages: int = 15
    min_silence_minutes: int = 5
    min_participants: int = 2
    required_activity_levels: list = field(default_factory=lambda: ["low", "medium"])
    required_topics: list = field(default_factory=list)
    cooldown_minutes: int = 30


@dataclass
class ChannelState:
    """Tracks state for a channel to prevent duplicate triggers"""
    last_summary_time: Optional[datetime] = None
    last_quiz_time: Optional[datetime] = None
    last_music_time: Optional[datetime] = None
    last_message_time: Optional[datetime] = None
    previous_activity_level: str = "inactive"
    message_count_at_last_trigger: int = 0


class TriggerManager:
    """
    Manages automatic triggering of bot features based on conversation state.

    This class monitors conversations and decides when to automatically
    execute features like summary, quiz, or music recommendations.
    """

    # Default trigger conditions
    DEFAULT_CONDITIONS = {
        TriggerType.SUMMARY: TriggerCondition(
            min_messages=15,
            min_silence_minutes=5,
            min_participants=1,
            required_activity_levels=["low", "inactive"],
            cooldown_minutes=30
        ),
        TriggerType.QUIZ: TriggerCondition(
            min_messages=20,
            min_silence_minutes=3,
            min_participants=2,
            required_activity_levels=["medium", "low"],
            cooldown_minutes=45
        ),
        TriggerType.MUSIC: TriggerCondition(
            min_messages=10,
            min_silence_minutes=2,
            min_participants=1,
            required_activity_levels=["low", "medium", "high"],
            required_topics=["音楽"],
            cooldown_minutes=60
        )
    }

    def __init__(self, bot=None):
        self.bot = bot
        self._running = False
        self._check_interval = 30  # Check every 30 seconds
        self._check_task = None
        self._channel_states: Dict[str, ChannelState] = {}
        self._conditions = dict(self.DEFAULT_CONDITIONS)
        self._enabled_features: Set[TriggerType] = {
            TriggerType.SUMMARY,
            TriggerType.QUIZ,
            TriggerType.MUSIC
        }
        # Deadline reminder: check every hour (120 iterations * 30s = 3600s = 1 hour)
        self._deadline_check_interval = 120
        self._deadline_check_counter = 0
        self._notified_deadlines: Set[str] = set()  # Track already-notified project IDs

    def get_channel_state(self, channel_id: str) -> ChannelState:
        """Get or create channel state"""
        if channel_id not in self._channel_states:
            self._channel_states[channel_id] = ChannelState()
        return self._channel_states[channel_id]

    def update_channel_state(
        self,
        channel_id: str,
        activity_level: str,
        message_time: Optional[datetime] = None
    ):
        """Update channel state after message"""
        state = self.get_channel_state(channel_id)
        state.previous_activity_level = activity_level
        if message_time:
            state.last_message_time = message_time

    async def start(self):
        """Start the trigger manager background task"""
        if self._running:
            logger.warning("Trigger manager already running")
            return

        self._running = True
        self._check_task = asyncio.create_task(self._monitor_loop())
        logger.info("Trigger manager started")

    async def stop(self):
        """Stop the trigger manager"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Trigger manager stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                await self._check_all_channels()

                # Check deadline reminders every hour
                self._deadline_check_counter += 1
                if self._deadline_check_counter >= self._deadline_check_interval:
                    self._deadline_check_counter = 0
                    await self._check_deadline_reminders()

                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trigger monitor loop: {e}")
                await asyncio.sleep(self._check_interval)

    async def _check_all_channels(self):
        """Check all active channels for trigger conditions"""
        if not self.bot or not self.bot.conversation_tracker:
            return

        # Get channels with recent activity
        active_channels = await self._get_active_channels()

        for channel_id in active_channels:
            try:
                await self._check_channel_triggers(channel_id)
            except Exception as e:
                logger.error(f"Error checking triggers for channel {channel_id}: {e}")

    async def _get_active_channels(self) -> list:
        """Get list of channels with recent activity"""
        if not self.bot:
            return []

        active_channels = []
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                channel_id = str(channel.id)
                state = self._channel_states.get(channel_id)

                # Include channels with recent messages
                if state and state.last_message_time:
                    time_since_last = datetime.now() - state.last_message_time
                    # Check channels active in last 30 minutes
                    if time_since_last < timedelta(minutes=30):
                        active_channels.append(channel_id)

        return active_channels

    async def _check_channel_triggers(self, channel_id: str):
        """Check if any triggers should fire for a channel"""
        if not self.bot or not self.bot.conversation_tracker:
            return

        # Get conversation data
        conversation = await self.bot.conversation_tracker.get_full_conversation(channel_id)
        if not conversation or not conversation.messages:
            return

        # Get conversation context
        context = await self.bot.conversation_tracker.conversation_analyzer.get_conversation_context(
            conversation.messages
        )

        # Check each enabled feature
        for trigger_type in self._enabled_features:
            if await self._should_trigger(channel_id, trigger_type, conversation.messages, context):
                await self._execute_trigger(channel_id, trigger_type, context)

    async def _should_trigger(
        self,
        channel_id: str,
        trigger_type: TriggerType,
        messages: list,
        context: Dict[str, Any]
    ) -> bool:
        """Determine if a trigger should fire"""
        condition = self._conditions.get(trigger_type)
        if not condition:
            return False

        state = self.get_channel_state(channel_id)
        now = datetime.now()

        # Check cooldown
        last_trigger_time = self._get_last_trigger_time(state, trigger_type)
        if last_trigger_time:
            time_since_last = now - last_trigger_time
            if time_since_last < timedelta(minutes=condition.cooldown_minutes):
                return False

        # Check message count
        if len(messages) < condition.min_messages:
            return False

        # Check silence (time since last message)
        last_message_time = messages[-1].timestamp if messages else None
        if last_message_time:
            silence_duration = now - last_message_time
            if silence_duration < timedelta(minutes=condition.min_silence_minutes):
                return False

        # Check participant count
        activity = context.get("activity", {})
        participant_count = activity.get("participant_count", 0)
        if participant_count < condition.min_participants:
            return False

        # Check activity level
        activity_level = activity.get("activity_level", "inactive")
        if activity_level not in condition.required_activity_levels:
            return False

        # Check required topics (if any)
        if condition.required_topics:
            topics = context.get("topics", [])
            if not any(topic in topics for topic in condition.required_topics):
                # For music, also trigger on positive sentiment without topic
                if trigger_type == TriggerType.MUSIC:
                    sentiment = context.get("sentiment")
                    if sentiment not in ["positive", "excited", "relaxed"]:
                        return False
                else:
                    return False

        # Check if enough new messages since last trigger
        if len(messages) <= state.message_count_at_last_trigger + 5:
            return False

        logger.info(f"Trigger conditions met for {trigger_type.value} in channel {channel_id}")
        return True

    def _get_last_trigger_time(self, state: ChannelState, trigger_type: TriggerType) -> Optional[datetime]:
        """Get the last trigger time for a specific type"""
        if trigger_type == TriggerType.SUMMARY:
            return state.last_summary_time
        elif trigger_type == TriggerType.QUIZ:
            return state.last_quiz_time
        elif trigger_type == TriggerType.MUSIC:
            return state.last_music_time
        return None

    def _update_trigger_time(self, state: ChannelState, trigger_type: TriggerType, messages_count: int):
        """Update the last trigger time for a specific type"""
        now = datetime.now()
        state.message_count_at_last_trigger = messages_count

        if trigger_type == TriggerType.SUMMARY:
            state.last_summary_time = now
        elif trigger_type == TriggerType.QUIZ:
            state.last_quiz_time = now
        elif trigger_type == TriggerType.MUSIC:
            state.last_music_time = now

    async def _execute_trigger(
        self,
        channel_id: str,
        trigger_type: TriggerType,
        context: Dict[str, Any]
    ):
        """Execute the triggered feature"""
        if not self.bot:
            return

        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.error(f"Channel {channel_id} not found for trigger execution")
            return

        state = self.get_channel_state(channel_id)
        messages = context.get("activity", {}).get("message_count", 0)

        try:
            if trigger_type == TriggerType.SUMMARY:
                await self._execute_summary_trigger(channel, channel_id)
            elif trigger_type == TriggerType.QUIZ:
                await self._execute_quiz_trigger(channel, channel_id)
            elif trigger_type == TriggerType.MUSIC:
                await self._execute_music_trigger(channel, channel_id, context)

            # Update state after successful execution
            self._update_trigger_time(state, trigger_type, messages)

        except Exception as e:
            logger.error(f"Failed to execute {trigger_type.value} trigger: {e}")

    async def _execute_summary_trigger(self, channel, channel_id: str):
        """Execute automatic summary"""
        if not self.bot.conversation_summarizer:
            logger.warning("Conversation summarizer not available")
            return

        # Get summary data
        summary_data = await self.bot.conversation_tracker.get_conversation_summary_data(channel_id)
        if not summary_data or not summary_data.get("messages"):
            return

        # Get guild ID
        guild_id = str(channel.guild.id)

        # Generate summary
        summary = await self.bot.conversation_summarizer.generate_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=summary_data["messages"]
        )

        if summary:
            formatted_summary = await self.bot.conversation_summarizer.format_summary_for_discord(summary)
            intro = "💡 会話が一段落したみたいだね！ここまでの流れをまとめてみたよ♪\n\n"
            await channel.send(intro + formatted_summary)
            logger.info(f"Auto summary executed for channel {channel_id}")

    async def _execute_quiz_trigger(self, channel, channel_id: str):
        """Execute automatic quiz"""
        if not self.bot.quiz_generator or not self.bot.quiz_runner:
            logger.warning("Quiz components not available")
            return

        # Check if quiz already active
        if await self.bot.quiz_runner.is_quiz_active(channel_id):
            return

        # Get recent messages
        recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
            channel_id, duration_minutes=60
        )

        if len(recent_messages) < 15:
            return

        guild_id = str(channel.guild.id)

        # Generate quiz
        quiz = await self.bot.quiz_generator.generate_quiz(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=recent_messages
        )

        if quiz and await self.bot.quiz_runner.start_quiz(channel_id, quiz):
            question_info = await self.bot.quiz_runner.get_current_question(channel_id)
            if question_info:
                question_text = self.bot.quiz_generator.format_question_for_discord(
                    question_info["question"],
                    question_info["question_number"],
                    question_info["total_questions"]
                )
                intro = "🎮 盛り上がってきたね！ここでクイズタイム！今までの会話からクイズを出すよ♪\n\n"
                await channel.send(intro + question_text)
                logger.info(f"Auto quiz executed for channel {channel_id}")

    async def _execute_music_trigger(self, channel, channel_id: str, context: Dict[str, Any]):
        """Execute automatic music recommendation"""
        if not self.bot.music_recommender:
            logger.warning("Music recommender not available")
            return

        # Get recent messages
        recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
            channel_id, duration_minutes=30
        )

        if not recent_messages:
            return

        guild_id = str(channel.guild.id)

        # Generate recommendation
        recommendation = await self.bot.music_recommender.generate_recommendation(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=recent_messages
        )

        if recommendation:
            formatted = self.bot.music_recommender.format_recommendation_for_discord(recommendation)
            intro = "🎵 今の雰囲気にぴったりの曲を見つけたよ！\n\n"
            await channel.send(intro + formatted)
            logger.info(f"Auto music recommendation executed for channel {channel_id}")

    async def _check_deadline_reminders(self):
        """Check for upcoming deadlines and send reminders"""
        if not self.bot:
            return

        levemagi_client = getattr(self.bot, "levemagi_client", None)
        if levemagi_client is None:
            return

        notifier = LeveMagiNotifier(self.bot)
        now = datetime.now()

        try:
            # Iterate over all guilds and their members to find users with deadlines
            for guild in self.bot.guilds:
                for member in guild.members:
                    if member.bot:
                        continue

                    discord_id = str(member.id)

                    try:
                        nuts_list = await levemagi_client.get_all_nuts(discord_id)
                    except Exception:
                        continue

                    for nuts in nuts_list:
                        # Skip completed projects or those without deadlines
                        if nuts.status == "完了" or not nuts.deadline:
                            continue

                        # Create a notification key to avoid duplicate reminders
                        notify_key = f"{discord_id}:{nuts.id}:{now.strftime('%Y-%m-%d-%H')}"
                        if notify_key in self._notified_deadlines:
                            continue

                        try:
                            deadline_dt = datetime.fromisoformat(nuts.deadline)
                        except (ValueError, TypeError):
                            # Try parsing date-only format
                            try:
                                deadline_dt = datetime.strptime(nuts.deadline, "%Y-%m-%d")
                            except (ValueError, TypeError):
                                continue

                        hours_remaining = (deadline_dt - now).total_seconds() / 3600

                        # Only notify for deadlines within 24 hours
                        if hours_remaining > 24:
                            continue

                        # Skip deadlines that are already more than 2 hours past
                        if hours_remaining < -2:
                            continue

                        # Find a channel to send the notification to
                        # Prefer the first text channel the bot can send messages to
                        target_channel = None
                        for channel in guild.text_channels:
                            permissions = channel.permissions_for(guild.me)
                            if permissions.send_messages:
                                target_channel = channel
                                break

                        if target_channel is None:
                            continue

                        # Send deadline reminder
                        await notifier.notify_deadline_reminder(
                            target_channel,
                            discord_id,
                            nuts.name,
                            nuts.deadline,
                            hours_remaining,
                        )
                        self._notified_deadlines.add(notify_key)

                        logger.info(
                            f"Sent deadline reminder for project '{nuts.name}' "
                            f"to user {discord_id} ({hours_remaining:.1f}h remaining)"
                        )

            # Clean up old notification keys (keep last 24 hours worth)
            if len(self._notified_deadlines) > 1000:
                self._notified_deadlines.clear()

        except Exception as e:
            logger.error(f"Error checking deadline reminders: {e}")

    # Configuration methods
    def enable_feature(self, trigger_type: TriggerType):
        """Enable a feature trigger"""
        self._enabled_features.add(trigger_type)
        logger.info(f"Enabled trigger: {trigger_type.value}")

    def disable_feature(self, trigger_type: TriggerType):
        """Disable a feature trigger"""
        self._enabled_features.discard(trigger_type)
        logger.info(f"Disabled trigger: {trigger_type.value}")

    def set_condition(self, trigger_type: TriggerType, condition: TriggerCondition):
        """Set custom condition for a trigger type"""
        self._conditions[trigger_type] = condition
        logger.info(f"Updated condition for trigger: {trigger_type.value}")

    def set_check_interval(self, seconds: int):
        """Set the check interval in seconds"""
        self._check_interval = max(10, seconds)  # Minimum 10 seconds
        logger.info(f"Check interval set to {self._check_interval} seconds")
