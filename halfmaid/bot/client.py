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
        self.tree.add_command(_play)
        self.tree.add_command(_volume)
        self.tree.add_command(_pause)
        self.tree.add_command(_playnow)
        self.tree.add_command(_info)
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


def _get_user_voice_channel(interaction: discord.Interaction) -> str | None:
    """Get the user's current voice channel ID, or None."""
    if interaction.user.voice and interaction.user.voice.channel:
        return str(interaction.user.voice.channel.id)
    return None


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


@app_commands.command(name="play", description="曲を再生またはキューに追加")
@app_commands.describe(query="曲名、アーティスト名、またはURL")
async def _play(interaction: discord.Interaction, query: str):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    channel_id = _get_user_voice_channel(interaction)
    if not channel_id:
        await interaction.response.send_message(
            "ボイスチャンネルに参加してください", ephemeral=True
        )
        return

    await interaction.response.defer()

    guild_id = str(interaction.guild_id)
    result = await vm.play(
        guild_id=guild_id,
        query=query,
        channel_id=channel_id,
        requester=interaction.user.display_name,
    )

    if not result.get("success"):
        await interaction.followup.send(
            result.get("error", "再生に失敗しました"), ephemeral=True
        )
        return

    track = result["track"]
    action = result["action"]

    embed = discord.Embed(color=0x1DB954)
    embed.set_author(
        name="Now Playing" if action == "playing" else "Queued",
        icon_url=interaction.client.user.display_avatar.url,
    )
    embed.title = track["title"]
    embed.url = track.get("url", "")
    if track.get("artist"):
        embed.add_field(name="Artist", value=track["artist"], inline=True)
    embed.add_field(
        name="Duration",
        value=f"`{_format_duration(track.get('duration_seconds', 0))}`",
        inline=True,
    )
    if action == "queued":
        pos = result.get("position_in_queue", 0)
        embed.add_field(name="Position", value=f"#{pos + 1}", inline=True)
    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.followup.send(embed=embed)


@app_commands.command(name="volume", description="音量を設定（0-100）")
@app_commands.describe(level="音量レベル（0-100）")
async def _volume(interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    result = await vm.set_volume(guild_id, level)
    await interaction.response.send_message(f"Volume set to {result['volume']}%")


@app_commands.command(name="pause", description="一時停止/再開をトグル")
async def _pause(interaction: discord.Interaction):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    status = vm.get_status(guild_id)

    if status.get("paused"):
        result = await vm.resume(guild_id)
        if result.get("success"):
            await interaction.response.send_message("Resumed!")
        else:
            await interaction.response.send_message(
                result.get("error", "再開に失敗しました"), ephemeral=True
            )
    elif status.get("playing"):
        result = await vm.pause(guild_id)
        if result.get("success"):
            await interaction.response.send_message("Paused!")
        else:
            await interaction.response.send_message(
                result.get("error", "一時停止に失敗しました"), ephemeral=True
            )
    else:
        await interaction.response.send_message("再生中ではありません", ephemeral=True)


@app_commands.command(name="playnow", description="キューをスキップして即座に再生")
@app_commands.describe(query="曲名、アーティスト名、またはURL")
async def _playnow(interaction: discord.Interaction, query: str):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    channel_id = _get_user_voice_channel(interaction)
    if not channel_id:
        await interaction.response.send_message(
            "ボイスチャンネルに参加してください", ephemeral=True
        )
        return

    await interaction.response.defer()

    guild_id = str(interaction.guild_id)
    result = await vm.play(
        guild_id=guild_id,
        query=query,
        channel_id=channel_id,
        requester=interaction.user.display_name,
        force=True,
    )

    if not result.get("success"):
        await interaction.followup.send(
            result.get("error", "再生に失敗しました"), ephemeral=True
        )
        return

    track = result["track"]

    embed = discord.Embed(color=0xFF4500)
    embed.set_author(
        name="Now Playing (Force)",
        icon_url=interaction.client.user.display_avatar.url,
    )
    embed.title = track["title"]
    embed.url = track.get("url", "")
    if track.get("artist"):
        embed.add_field(name="Artist", value=track["artist"], inline=True)
    embed.add_field(
        name="Duration",
        value=f"`{_format_duration(track.get('duration_seconds', 0))}`",
        inline=True,
    )
    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.followup.send(embed=embed)


@app_commands.command(name="info", description="再生状態・設定の詳細を表示")
async def _info(interaction: discord.Interaction):
    vm = _get_vm()
    if not vm:
        await interaction.response.send_message("音楽ボットが準備中です", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    status = vm.get_status(guild_id)
    gq = vm.queue.get(guild_id)

    embed = discord.Embed(title="HalfMaid Status", color=0x5865F2)

    # Connection
    if status["connected"]:
        embed.add_field(
            name="Connection",
            value=f"**{status['channel_name']}**",
            inline=False,
        )
    else:
        embed.add_field(name="Connection", value="Not connected", inline=False)

    # Current track with progress bar
    if status["current_track"]:
        track = status["current_track"]
        elapsed = track.get("elapsed_seconds", 0)
        duration = track.get("duration_seconds", 0)

        bar_length = 12
        filled = int(bar_length * elapsed / duration) if duration > 0 else 0
        bar = "▓" * filled + "░" * (bar_length - filled)

        state_icon = "⏸️" if status["paused"] else "▶️"
        track_text = (
            f"{state_icon} [{track['title']}]({track.get('url', '')})\n"
            f"{track.get('artist', 'Unknown')}\n"
            f"`{bar}` `{_format_duration(elapsed)} / {_format_duration(duration)}`"
        )
        embed.add_field(name="Now Playing", value=track_text, inline=False)
    else:
        embed.add_field(name="Now Playing", value="Nothing playing", inline=False)

    # Queue
    total_duration = sum(t.duration_seconds for t in gq.tracks)
    queue_text = f"{len(gq.tracks)} tracks"
    if total_duration > 0:
        queue_text += f" ({_format_duration(total_duration)})"
    embed.add_field(name="Queue", value=queue_text, inline=True)

    # Settings
    settings_lines = [
        f"Volume: {gq.volume}%",
        f"Loop: {gq.loop_mode}",
        f"Shuffle: {'on' if gq.shuffle else 'off'}",
        f"Autoplay: {'on' if status.get('autoplay') else 'off'}",
    ]
    embed.add_field(name="Settings", value="\n".join(settings_lines), inline=True)

    await interaction.response.send_message(embed=embed)
