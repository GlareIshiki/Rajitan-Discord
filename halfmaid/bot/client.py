"""Discord bot client for music playback."""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

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

    async def setup_hook(self):
        """Register slash commands on startup."""
        self.tree.add_command(_np)
        self.tree.add_command(_queue)
        self.tree.add_command(_skip)
        self.tree.add_command(_stop)
        synced = await self.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")

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


# --- Slash commands ---

def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _get_vm():
    from halfmaid.bot.voice import voice_manager
    return voice_manager


@app_commands.command(name="np", description="現在再生中の曲を表示")
async def _np(interaction: discord.Interaction):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    status = vm.get_status(guild_id)

    if not status["connected"] or not status["current_track"]:
        await interaction.response.send_message("現在再生中の曲はありません", ephemeral=True)
        return

    track = status["current_track"]
    elapsed = track.get("elapsed_seconds", 0)
    duration = track.get("duration_seconds", 0)

    embed = discord.Embed(
        title=track["title"],
        url=track.get("url", ""),
        color=0x1DB954,
    )
    embed.set_author(name="Now Playing", icon_url=interaction.client.user.display_avatar.url)
    if track.get("artist"):
        embed.add_field(name="Artist", value=track["artist"], inline=True)
    embed.add_field(
        name="Progress",
        value=f"`{_format_duration(elapsed)} / {_format_duration(duration)}`",
        inline=True,
    )
    if track.get("requester"):
        embed.add_field(name="Requested by", value=track["requester"], inline=True)
    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])

    footer_parts = []
    footer_parts.append(f"Vol: {status['volume']}%")
    if status["loop_mode"] != "off":
        footer_parts.append(f"Loop: {status['loop_mode']}")
    if status["shuffle"]:
        footer_parts.append("Shuffle: on")
    if status.get("autoplay"):
        footer_parts.append("Autoplay: on")
    embed.set_footer(text=" | ".join(footer_parts))

    await interaction.response.send_message(embed=embed)


@app_commands.command(name="queue", description="再生キューを表示")
async def _queue(interaction: discord.Interaction):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    status = vm.get_status(guild_id)
    gq = vm.queue.get(guild_id)
    queue_info = gq.get_queue_info()

    embed = discord.Embed(title="Music Queue", color=0x5865F2)

    # Now playing
    if status["current_track"]:
        track = status["current_track"]
        elapsed = track.get("elapsed_seconds", 0)
        duration = track.get("duration_seconds", 0)
        np_text = (
            f"[{track['title']}]({track.get('url', '')})\n"
            f"{track.get('artist', 'Unknown')} | "
            f"`{_format_duration(elapsed)} / {_format_duration(duration)}`"
        )
        embed.add_field(name="Now Playing", value=np_text, inline=False)
    else:
        embed.add_field(name="Now Playing", value="Nothing playing", inline=False)

    # Queue
    tracks = queue_info.get("tracks", [])
    if tracks:
        lines = []
        for i, t in enumerate(tracks[:10]):
            dur = _format_duration(t.get("duration_seconds", 0))
            lines.append(f"`{i+1}.` {t['title']} — {t.get('artist', '?')} `{dur}`")
        if len(tracks) > 10:
            lines.append(f"*...and {len(tracks) - 10} more*")
        embed.add_field(name=f"Up Next ({len(tracks)} tracks)", value="\n".join(lines), inline=False)
    else:
        auto_text = "Autoplay will find the next track" if status.get("autoplay") else "Queue is empty"
        embed.add_field(name="Up Next", value=auto_text, inline=False)

    # Footer
    footer_parts = [f"Vol: {status['volume']}%"]
    if status["loop_mode"] != "off":
        footer_parts.append(f"Loop: {status['loop_mode']}")
    if status["shuffle"]:
        footer_parts.append("Shuffle: on")
    if status.get("autoplay"):
        footer_parts.append("Autoplay: on")
    embed.set_footer(text=" | ".join(footer_parts))

    await interaction.response.send_message(embed=embed)


@app_commands.command(name="skip", description="現在の曲をスキップ")
async def _skip(interaction: discord.Interaction):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    result = await vm.skip(guild_id)
    if result.get("success"):
        await interaction.response.send_message("Skipped!")
    else:
        await interaction.response.send_message(result.get("error", "スキップ失敗"), ephemeral=True)


@app_commands.command(name="stop", description="音楽を停止してVCから退出")
async def _stop(interaction: discord.Interaction):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    await vm.stop(guild_id)
    await interaction.response.send_message("Stopped and disconnected.")
