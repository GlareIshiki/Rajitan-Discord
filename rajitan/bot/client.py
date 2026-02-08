import asyncio
import discord
from discord.ext import commands
from typing import Optional, Dict, Any, List
from datetime import datetime
from rajitan.storage.models import Message
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config
from rajitan.utils.validators import validate_guild_id, validate_channel_id
from rajitan.nlp.intent_classifier import IntentClassifier, ScheduleParser, ConfirmationGenerator, IntentType
from rajitan.nlp.intent_strategy import IntentRouter

logger = get_logger("discord_client")
config = get_config()


class RajitanBot(commands.Bot):
    """Main Discord bot client for Rajitan"""
    
    def __init__(self, **kwargs):
        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        
        # Initialize bot
        super().__init__(
            command_prefix='!rajitan ',
            intents=intents,
            help_command=None,
            **kwargs
        )
        
        # Bot components (will be injected)
        self.db_client = None
        self.redis_client = None
        self.character_manager = None
        self.conversation_tracker = None
        self.conversation_summarizer = None
        self.quiz_generator = None
        self.quiz_runner = None
        self.enhanced_schedule_manager = None
        self.trigger_manager = None
        self.music_recommender = None
        self.levemagi_client = None
        
        # Bot state
        self.start_time = None
        self.ready = False
        self.intent_router = None
    
    def inject_dependencies(self, **dependencies):
        """Inject service dependencies"""
        for name, service in dependencies.items():
            setattr(self, name, service)
        logger.info("Dependencies injected into bot")
    
    async def on_ready(self):
        """Called when bot is ready"""
        try:
            self.start_time = datetime.now()
            self.ready = True
            
            logger.info(f'{self.user} has connected to Discord!')
            logger.info(f'Bot is in {len(self.guilds)} guilds')
            
            # Set bot status
            activity = discord.Activity(
                type=discord.ActivityType.listening, 
                name="!rajitan help"
            )
            await self.change_presence(activity=activity)
            
            # Ensure default character exists for all guilds
            if self.character_manager:
                for guild in self.guilds:
                    try:
                        character = await self.character_manager.get_character(str(guild.id))
                        if not character:
                            await self.character_manager.create_character(
                                guild_id=str(guild.id), name="らじたん"
                            )
                            logger.info(f"Created default character for guild: {guild.name}")
                    except Exception as e:
                        logger.error(f"Failed to create default character for {guild.name}: {e}")

            # Sync slash commands if in debug mode
            if config.debug:
                try:
                    synced = await self.tree.sync()
                    logger.info(f"Synced {len(synced)} command(s)")
                except Exception as e:
                    logger.error(f"Failed to sync commands: {e}")
            
        except Exception as e:
            logger.error(f"Error in on_ready: {e}")
    
    async def on_guild_join(self, guild: discord.Guild):
        """Called when bot joins a guild"""
        if guild is None:
            logger.error("guild is None in on_guild_join")
            return
        try:
            logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")
            
            # Register guild in database
            if self.db_client is not None:
                from rajitan.storage.models import Guild
                guild_model = Guild(
                    id=str(guild.id),
                    name=guild.name
                )
                await self.db_client.create_guild(guild_model)
            
            # Create default character
            if self.character_manager is not None:
                await self.character_manager.create_character(
                    guild_id=str(guild.id),
                    name="Rajitan"
                )
            
        except Exception as e:
            logger.error(f"Error handling guild join: {e}")
    
    async def on_guild_remove(self, guild: discord.Guild):
        """Called when bot leaves a guild"""
        if guild is None:
            logger.error("guild is None in on_guild_remove")
            return
        try:
            logger.info(f"Left guild: {guild.name} (ID: {guild.id})")
            
        except Exception as e:
            logger.error(f"Error handling guild remove: {e}")
    
    async def on_message(self, message: discord.Message):
        """Handle incoming messages"""
        if message is None or message.author is None:
            return
        if self.conversation_tracker is None:
            return
        try:
            # Ignore bot messages
            if message.author.bot:
                return
            
            # Ignore DMs
            if not message.guild:
                return
            
            # Track conversation
            await self.conversation_tracker.track_message(
                channel_id=str(message.channel.id),
                user_id=str(message.author.id),
                username=message.author.display_name,
                content=message.content
            )

            # Update trigger manager state
            if self.trigger_manager:
                from datetime import datetime
                # Get current activity level
                recent_messages = await self.conversation_tracker.get_recent_conversation(
                    str(message.channel.id), duration_minutes=30
                )
                activity = await self.conversation_tracker.conversation_analyzer.analyze_conversation_activity(
                    recent_messages
                )
                self.trigger_manager.update_channel_state(
                    str(message.channel.id),
                    activity.get("activity_level", "inactive"),
                    datetime.now()
                )

            # Handle bot mentions
            if self.user is not None and self.user in message.mentions:
                channel_name = getattr(message.channel, 'name', str(message.channel.id))
                logger.info(f"Bot mentioned by {message.author.display_name} in channel {channel_name}")
                await self.handle_mention(message)
            
            # Process commands
            await self.process_commands(message)
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def handle_mention(self, message: discord.Message):
        """Handle when bot is mentioned"""
        if message is None or message.guild is None or message.channel is None:
            return
        if self.conversation_tracker is None or self.character_manager is None:
            return
        try:
            guild_id = str(message.guild.id)
            channel_id = str(message.channel.id)
            
            # Extract message content without mention
            content = message.content
            if self.user is not None:
                # Remove bot mention from content
                mention_patterns = [
                    f"<@{self.user.id}>",
                    f"<@!{self.user.id}>",
                    f"@{self.user.name}",
                    f"@{self.user.display_name}"
                ]
                for pattern in mention_patterns:
                    content = content.replace(pattern, "").strip()
            
            # If no content after removing mention, use a default message
            if not content:
                content = "Hello! How can I help you today?"
            
            # Process natural language intent
            await self.process_mention_with_nlp(message, content)
            
        except Exception as e:
            logger.error(f"Error handling mention: {e}")
            try:
                await message.channel.send("Sorry, I couldn't process your request due to an error.")
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")
    
    async def process_mention_with_nlp(self, message: discord.Message, content: str):
        """Process mention with natural language processing"""
        try:
            async with message.channel.typing():
                guild_id = str(message.guild.id)
                channel_id = str(message.channel.id)

                # Get recent conversation for context
                recent_messages = []
                try:
                    recent_messages = await self.conversation_tracker.get_recent_conversation(
                        channel_id, duration_minutes=30
                    )
                except Exception as e:
                    logger.warning(f"Could not get recent conversation: {e}")

                # Track this mention as a message
                try:
                    await self.conversation_tracker.track_message(
                        channel_id=channel_id,
                        user_id=str(message.author.id),
                        username=message.author.display_name,
                        content=content
                    )
                except Exception as e:
                    logger.warning(f"Could not track message: {e}")

                # Classify user intent
                intent_classifier = IntentClassifier()
                classification_result = await intent_classifier.classify_intent(content)

                intent = classification_result.get("intent")
                confidence = classification_result.get("confidence", 0.0)

                logger.info(f"Classified intent: {intent} (confidence: {confidence})")

                # Use intent router for clean handling
                if not self.intent_router:
                    self.intent_router = IntentRouter(self)

                await self.intent_router.route(message, content, classification_result)

        except Exception as e:
            logger.error(f"Error in NLP processing: {e}")
            # Fallback to simple response
            await message.channel.send("ごめん、今ちょっと調子が悪いみたい。もう一度話しかけてね！")
    
    
    async def create_schedule_from_parsed_data(self, message: discord.Message, schedule_data: Dict[str, Any]) -> bool:
        """Create schedule from parsed data"""
        try:
            from rajitan.scheduler.schedule_models import (
                ScheduleInfo, ExecutionTime, FunctionConfig, 
                ScheduleType, FunctionType, ExecutionPattern
            )
            
            # Extract schedule information
            execution_time_data = schedule_data.get("execution_time", {})
            function_config_data = schedule_data.get("function_config", {})
            
            # Create ExecutionTime object
            pattern = execution_time_data.get("pattern", "once")
            relative_minutes = execution_time_data.get("relative_minutes")
            
            # Handle different time specifications for one-time schedules
            specific_datetime = None
            if pattern == "once":
                if relative_minutes:
                    specific_datetime = datetime.now() + timedelta(minutes=relative_minutes)
                    logger.info(f"Calculated specific datetime for relative schedule: {specific_datetime}")
                elif execution_time_data.get("hour") is not None and execution_time_data.get("minute") is not None:
                    # For "today's HH:MM" format
                    hour = execution_time_data.get("hour")
                    minute = execution_time_data.get("minute")
                    today = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if today <= datetime.now():
                        # If time has passed today, schedule for tomorrow
                        today += timedelta(days=1)
                    specific_datetime = today
                    logger.info(f"Calculated specific datetime for today's time: {specific_datetime}")
                elif execution_time_data.get("specific_datetime"):
                    specific_datetime = execution_time_data.get("specific_datetime")
                    logger.info(f"Using provided specific datetime: {specific_datetime}")
            
            execution_time = ExecutionTime(
                pattern=ExecutionPattern(pattern),
                hour=execution_time_data.get("hour"),
                minute=execution_time_data.get("minute"),
                day_of_week=execution_time_data.get("day_of_week"),
                day_of_month=execution_time_data.get("day_of_month"),
                specific_datetime=specific_datetime or execution_time_data.get("specific_datetime"),
                relative_minutes=relative_minutes
            )
            
            # Create FunctionConfig object
            function_type = function_config_data.get("type", "custom_message")
            function_config = FunctionConfig(
                function_type=FunctionType(function_type),
                custom_message=function_config_data.get("custom_message"),
                parameters=function_config_data.get("parameters", {})
            )
            
            # Determine schedule type
            schedule_type = ScheduleType.PERIODIC if pattern in ["daily", "weekly", "monthly", "hourly"] else ScheduleType.ONE_TIME
            
            # Create ScheduleInfo object
            schedule_info = ScheduleInfo(
                channel_id=str(message.channel.id),
                guild_id=str(message.guild.id),
                schedule_type=schedule_type,
                execution_time=execution_time,
                function_config=function_config,
                created_by=str(message.author.id)
            )
            
            # Debug log schedule details
            logger.info(f"Creating schedule: {schedule_info.function_config.function_type} "
                       f"pattern={schedule_info.execution_time.pattern} "
                       f"hour={schedule_info.execution_time.hour} "
                       f"minute={schedule_info.execution_time.minute} "
                       f"next_execution={schedule_info.next_execution}")
            
            # Save schedule using enhanced manager
            if hasattr(self, 'enhanced_schedule_manager') and self.enhanced_schedule_manager:
                success = await self.enhanced_schedule_manager.create_schedule(schedule_info)
                if success:
                    logger.info(f"Schedule successfully created for channel {message.channel.id}")
                    # Verify schedule was saved
                    schedules = await self.enhanced_schedule_manager.get_channel_schedules(str(message.channel.id))
                    logger.info(f"Total schedules for channel: {len(schedules)}")
                    return True
                else:
                    logger.error("Failed to save schedule to database")
                    return False
            else:
                logger.error("Enhanced schedule manager not available")
                return False
            
        except Exception as e:
            logger.error(f"Error creating schedule: {e}")
            return False
    
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Handle command errors"""
        if ctx is None or error is None:
            return
        if not hasattr(ctx, 'send') or ctx.send is None:
            return
        try:
            if isinstance(error, commands.CommandNotFound):
                return  # Ignore unknown commands
            
            logger.error(f"Command error in {ctx.command}: {error}")
            
            if isinstance(error, commands.MissingPermissions):
                await ctx.send("You do not have permission to use this command.")
            elif isinstance(error, commands.BadArgument):
                await ctx.send("Invalid argument provided.")
            elif isinstance(error, commands.CommandOnCooldown):
                await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.1f} seconds.")
            else:
                await ctx.send("An unknown error occurred while processing your command.")
            
        except Exception as e:
            logger.error(f"Error in command error handler: {e}")
    
    async def send_message(self, channel_id: str, content: str, embed: Optional[discord.Embed] = None) -> bool:
        """Send message to a channel"""
        if channel_id is None or content is None:
            return False
        channel = self.get_channel(int(channel_id))
        if channel is None or not isinstance(channel, discord.TextChannel):
            return False
        try:
            if embed:
                await channel.send(content=content, embed=embed)
            else:
                await channel.send(content)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
    
    async def create_embed(
        self, 
        title: str, 
        description: str, 
        color: discord.Color = discord.Color.blue(),
        **kwargs
    ) -> discord.Embed:
        """Create a Discord embed"""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(),
            **kwargs
        )
        
        embed.set_footer(text="Rajitan", icon_url=self.user.avatar.url if self.user is not None and self.user.avatar else None)
        
        return embed
    
    def get_bot_stats(self) -> Dict[str, Any]:
        """Get bot statistics"""
        all_members = set(self.get_all_members())
        return {
            "guilds": len(self.guilds),
            "users": len(all_members),
            "humans": len([m for m in all_members if not m.bot]),
            "bots": len([m for m in all_members if m.bot]),
            "channels": len([c for c in self.get_all_channels() if isinstance(c, discord.TextChannel)]),
            "uptime": (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            "ready": self.ready,
            "latency": round(self.latency * 1000, 2)  # ms
        }

    def get_user_breakdown(self) -> Dict[str, Any]:
        """Get user breakdown by guild (humans vs bots)"""
        all_members = set(self.get_all_members())
        per_guild = []
        for guild in self.guilds:
            members = guild.members
            humans = len([m for m in members if not m.bot])
            bots = len([m for m in members if m.bot])
            per_guild.append({
                "id": str(guild.id),
                "name": guild.name,
                "humans": humans,
                "bots": bots,
                "total": humans + bots,
            })
        per_guild.sort(key=lambda g: g["total"], reverse=True)
        return {
            "total": len(all_members),
            "humans": len([m for m in all_members if not m.bot]),
            "bots": len([m for m in all_members if m.bot]),
            "per_guild": per_guild,
        }
    
    async def shutdown(self):
        """Gracefully shutdown the bot"""
        try:
            logger.info("Shutting down bot...")
            
            # Close database connections
            if self.db_client is not None:
                await self.db_client.close()
            
            if self.redis_client is not None:
                await self.redis_client.close()
            
            # Close bot connection
            await self.close()
            
            logger.info("Bot shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    async def is_admin(self, user: discord.Member) -> bool:
        """Check if user has admin permissions"""
        if user is None or not hasattr(user, 'guild_permissions'):
            return False
        return user.guild_permissions.administrator
    
    async def fetch_discord_history_as_messages(
        self,
        channel: discord.TextChannel,
        limit: int = 50
    ) -> List[Message]:
        """Fetch Discord channel history and convert to Message objects"""
        messages = []
        try:
            async for msg in channel.history(limit=limit, oldest_first=True):
                if msg.author.bot:
                    continue
                if not msg.content:
                    continue
                messages.append(Message(
                    user_id=str(msg.author.id),
                    username=msg.author.display_name,
                    content=msg.content,
                    timestamp=msg.created_at.replace(tzinfo=None)
                ))
        except Exception as e:
            logger.error(f"Failed to fetch Discord history: {e}")
        return messages

    async def has_manage_permissions(self, user: discord.Member) -> bool:
        """Check if user has manage permissions"""
        if user is None or not hasattr(user, 'guild_permissions'):
            return False
        return (
            user.guild_permissions.administrator or 
            user.guild_permissions.manage_guild or
            user.guild_permissions.manage_channels
        )