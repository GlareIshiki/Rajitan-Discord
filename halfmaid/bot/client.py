"""Discord bot client for music playback."""

import discord
from discord.ext import commands

from halfmaid.utils.logger import get_logger

logger = get_logger("bot.client")

# Load opus library for voice support
if not discord.opus.is_loaded():
    try:
        discord.opus.load_opus("libopus.so.0")
        logger.info("Opus library loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load opus library: {e}")


class HalfMaidBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        logger.info(f"HalfMaid ready: {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Auto-disconnect when voice channel becomes empty."""
        if member.id == self.user.id:
            return

        voice_client = member.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return

        channel = voice_client.channel
        # Count non-bot members
        members = [m for m in channel.members if not m.bot]
        if not members:
            logger.info(f"Voice channel empty in guild {member.guild.id}, disconnecting")
            from halfmaid.bot.voice import voice_manager
            await voice_manager.stop(str(member.guild.id))
