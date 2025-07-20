import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
from rajitan.utils.logger import get_logger
from rajitan.utils.validators import validate_system_prompt, validate_character_name, validate_interval

logger = get_logger("discord_commands")


class RajitanCommands(commands.Cog):
    """Discord slash commands for Rajitan"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="setup", description="Setup character for this guild")
    @app_commands.describe(
        name="Character name (default: Rajitan)",
        personality="Character personality type",
        system_prompt="Custom system prompt for character"
    )
    async def setup_character(
        self,
        interaction: discord.Interaction,
        name: Optional[str] = "Rajitan",
        personality: Optional[Literal["default", "cheerful", "calm", "witty"]] = "default",
        system_prompt: Optional[str] = None
    ):
        """Setup character for the guild"""
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a guild.",
                ephemeral=True
            )
            return
        try:
            # Check permissions
            if not await self.bot.has_manage_permissions(interaction.user):
                await interaction.response.send_message(
                    "You do not have permission to use this command.",
                    ephemeral=True
                )
                return
            
            # Validate inputs
            if name and not validate_character_name(name):
                await interaction.response.send_message(
                    "Invalid character name. Must be 1-32 characters long.",
                    ephemeral=True
                )
                return
            
            if system_prompt and not validate_system_prompt(system_prompt):
                await interaction.response.send_message(
                    "Invalid system prompt. Must be 10-2000 characters long.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            
            # Create character
            success = await self.bot.character_manager.create_character(
                guild_id=str(interaction.guild.id),
                name=name,
                system_prompt=system_prompt,
                personality_type=personality
            )
            
            if success:
                embed = await self.bot.create_embed(
                    title="Character Setup Complete",
                    description=f"**{name}** has been set up successfully!\n\n"
                               f"Personality: {personality}\n"
                               f"Ready to chat!",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "Failed to create character. Please try again."
                )
            
        except Exception as e:
            logger.error(f"Error in setup command: {e}")
            await interaction.followup.send(
                "An error occurred while setting up the character."
            )
    
    @app_commands.command(name="chat", description="Private chat with character")
    @app_commands.describe(message="Message to send to character")
    async def chat(self, interaction: discord.Interaction, message: str):
        """Private chat with character - only visible to you"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "This command can only be used in a guild channel.",
                ephemeral=True
            )
            return
        try:
            # Defer with ephemeral=True to make it private
            await interaction.response.defer(ephemeral=True)
            
            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)
            
            # Get recent conversation for context
            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=30
            )
            
            # Track private chat message
            await self.bot.conversation_tracker.track_message(
                channel_id=channel_id,
                user_id=str(interaction.user.id),
                username=interaction.user.display_name,
                content=f"[PRIVATE] {message}"
            )
            
            # Generate response
            response = await self.bot.character_manager.generate_response(
                guild_id=guild_id,
                messages=recent_messages,
                user_message=message,
                context={"channel_id": channel_id, "private_chat": True}
            )
            
            if response:
                # Create embed for private response
                embed = discord.Embed(
                    title="💬 Private Chat",
                    description=f"**Your message:** {message}\n\n**Response:** {response}",
                    color=discord.Color.purple()
                )
                embed.set_footer(text="This message is only visible to you")
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                # Track bot response
                await self.bot.conversation_tracker.track_message(
                    channel_id=channel_id,
                    user_id=str(self.bot.user.id) if self.bot.user else "bot",
                    username=self.bot.user.display_name if self.bot.user else "Rajitan",
                    content=f"[PRIVATE] {response}"
                )
            else:
                await interaction.followup.send(
                    "I'm here to help! (no response generated)",
                    ephemeral=True
                )
            
        except Exception as e:
            logger.error(f"Error in chat command: {e}")
            await interaction.followup.send(
                "An error occurred while processing your message.",
                ephemeral=True
            )
    
    @app_commands.command(name="summary", description="Generate conversation summary")
    async def manual_summary(self, interaction: discord.Interaction):
        """Manually trigger conversation summary"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "This command can only be used in a guild channel.",
                ephemeral=True
            )
            return
        try:
            await interaction.response.defer()
            
            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)
            
            # Get conversation data
            summary_data = await self.bot.conversation_tracker.get_conversation_summary_data(channel_id)
            
            if not summary_data or not summary_data["messages"]:
                await interaction.followup.send(
                    "No recent conversation found to summarize."
                )
                return
            
            # Generate summary
            summary = await self.bot.conversation_summarizer.generate_summary(
                guild_id=guild_id,
                channel_id=channel_id,
                messages=summary_data["messages"]
            )
            
            if summary:
                formatted_summary = await self.bot.conversation_summarizer.format_summary_for_discord(summary)
                embed = await self.bot.create_embed(
                    title="Conversation Summary",
                    description=formatted_summary,
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "Failed to generate summary. Please try again."
                )
            
        except Exception as e:
            logger.error(f"Error in summary command: {e}")
            await interaction.followup.send(
                "An error occurred while generating the summary."
            )
    
    @app_commands.command(name="quiz", description="Start a quiz based on conversation")
    async def start_quiz(self, interaction: discord.Interaction):
        """Start a quiz based on conversation"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "This command can only be used in a guild channel.",
                ephemeral=True
            )
            return
        try:
            await interaction.response.defer()
            
            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)
            
            # Check if quiz is already active
            if await self.bot.quiz_runner.is_quiz_active(channel_id):
                await interaction.followup.send(
                    "A quiz is already active in this channel."
                )
                return
            
            # Get conversation data
            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=60
            )
            
            if len(recent_messages) < 15:
                await interaction.followup.send(
                    "Not enough conversation data to generate a quiz. Need at least 15 messages."
                )
                return
            
            # Generate quiz
            quiz = await self.bot.quiz_generator.generate_quiz(
                guild_id=guild_id,
                channel_id=channel_id,
                messages=recent_messages
            )
            
            if not quiz:
                await interaction.followup.send(
                    "Failed to generate quiz. Please try again."
                )
                return
            
            # Start quiz
            success = await self.bot.quiz_runner.start_quiz(channel_id, quiz)
            
            if success:
                # Get first question
                question_info = await self.bot.quiz_runner.get_current_question(channel_id)
                if question_info:
                    question_text = self.bot.quiz_generator.format_question_for_discord(
                        question_info["question"],
                        question_info["question_number"],
                        question_info["total_questions"]
                    )
                    
                    embed = await self.bot.create_embed(
                        title="Quiz Question",
                        description=question_text,
                        color=discord.Color.gold()
                    )
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(
                        "Failed to get quiz question. Please try again."
                    )
            else:
                await interaction.followup.send(
                    "Failed to start quiz. Please try again."
                )
            
        except Exception as e:
            logger.error(f"Error in quiz command: {e}")
            await interaction.followup.send(
                "An error occurred while starting the quiz."
            )
    
    @app_commands.command(name="status", description="Show bot status")
    async def status_command(self, interaction: discord.Interaction):
        """Show bot status"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "This command can only be used in a guild channel.",
                ephemeral=True
            )
            return
        try:
            stats = self.bot.get_bot_stats()
            
            # Get character info
            character_info = await self.bot.character_manager.get_character_info(
                str(interaction.guild.id)
            )
            
            # Get conversation stats
            conversation_stats = await self.bot.conversation_tracker.get_conversation_stats(
                str(interaction.channel.id)
            )
            
            embed = await self.bot.create_embed(
                title="Bot Status",
                description="Here's the current status of the bot.",
                color=discord.Color.blue()
            )
            
            # Bot stats
            uptime_hours = round(stats["uptime"] / 3600, 1)
            embed.add_field(
                name="Bot Uptime",
                value=f"Bot has been online for {uptime_hours} hours.\n"
                      f"Latency: {stats['latency']}ms\n"
                      f"Guilds: {stats['guilds']}",
                inline=True
            )
            
            # Character info
            if character_info:
                embed.add_field(
                    name="Current Character",
                    value=f"Name: {character_info['name']}\n"
                          f"Personality: {character_info['personality_type']}\n"
                          f"Created: {character_info['created_at'].strftime('%Y/%m/%d')}",
                    inline=True
                )
            
            # Conversation stats
            embed.add_field(
                name="Conversation Stats",
                value=f"Is Active: {'Yes' if conversation_stats['is_active'] else 'No'}\n"
                      f"Messages: {conversation_stats['message_count']}\n"
                      f"Participants: {conversation_stats['participant_count']}",
                inline=True
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await interaction.response.send_message(
                "An error occurred while fetching bot status."
            )
    
    @app_commands.command(name="help", description="Show help information")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information"""
        try:
            embed = await self.bot.create_embed(
                title="Help",
                description="Here's how to use the bot commands.",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Available Commands",
                value="`/setup` - Setup a character for this guild.\n"
                      "`/status` - Show bot status and current character.\n"
                      "`/chat` - Send a message to the character.\n"
                      "`/summary` - Generate a summary of the current conversation.\n"
                      "`/quiz` - Start a quiz based on the conversation.",
                inline=False
            )
            
            embed.add_field(
                name="How to Use",
                value="To use a command, type it in the chat and the bot will respond.\n"
                      "For example: `/setup` to set up a character.\n"
                      "You can also use the slash commands from the bot's menu.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await interaction.response.send_message(
                "An error occurred while showing help."
            )


async def setup(bot):
    """Setup commands cog"""
    await bot.add_cog(RajitanCommands(bot))