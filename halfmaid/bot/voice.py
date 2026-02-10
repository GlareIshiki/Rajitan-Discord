"""Voice playback manager — handles yt-dlp + FFmpeg + discord.py voice."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import discord

from halfmaid.config import get_config
from halfmaid.queue.manager import QueueManager
from halfmaid.queue.models import Track
from halfmaid.utils.logger import get_logger
from halfmaid.utils.ytdlp import YtDlpExtractor

logger = get_logger("bot.voice")

FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"


@dataclass
class GuildVoiceState:
    current_track: Optional[Track] = None
    start_time: Optional[datetime] = None
    idle_task: Optional[asyncio.Task] = None


class VoiceManager:
    """Manages voice connections and playback for all guilds."""

    def __init__(self, bot: discord.Client, queue_manager: QueueManager):
        self.bot = bot
        self.queue = queue_manager
        self.extractor = YtDlpExtractor()
        self._states: dict[str, GuildVoiceState] = {}
        self._config = get_config()

    def _state(self, guild_id: str) -> GuildVoiceState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildVoiceState()
        return self._states[guild_id]

    def _voice_client(self, guild_id: str) -> Optional[discord.VoiceClient]:
        guild = self.bot.get_guild(int(guild_id))
        if guild:
            return guild.voice_client
        return None

    async def play(
        self,
        guild_id: str,
        query: str,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
        requester: str = "",
    ) -> dict:
        """Play a track or add to queue."""
        logger.info(f"play() called: guild={guild_id}, query={query[:50]}, user={user_id}")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            logger.error(f"Guild not found: {guild_id}")
            return {"success": False, "error": "ギルドが見つかりません"}

        # Resolve voice channel
        voice_channel = await self._resolve_channel(guild, channel_id, user_id)
        if not voice_channel:
            return {
                "success": False,
                "error": "ボイスチャンネルが見つかりません。ユーザーがボイスチャンネルに参加している必要があります",
            }

        # Extract track info
        track_info = await self.extractor.extract(query)
        if not track_info:
            return {"success": False, "error": f"曲が見つかりません: {query}"}

        track = Track(
            title=track_info.title,
            artist=track_info.artist,
            url=track_info.url,
            stream_url=track_info.stream_url,
            duration_seconds=track_info.duration_seconds,
            thumbnail=track_info.thumbnail,
            requester=requester,
        )

        # Join voice channel if needed
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            t0 = time.monotonic()
            logger.info(f"Connecting to VC: {voice_channel.name} ({voice_channel.id}), opus={discord.opus.is_loaded()}")
            try:
                vc = await voice_channel.connect(timeout=15.0, reconnect=False)
            except Exception as e:
                elapsed = time.monotonic() - t0
                logger.error(f"connect() raised {type(e).__name__} after {elapsed:.1f}s: {e}")
                return {"success": False, "error": f"ボイスチャンネルに接続できません: {e}"}

            # Wait for voice connection to be fully established
            for _ in range(20):
                if vc.is_connected():
                    break
                await asyncio.sleep(0.25)

            if not vc.is_connected():
                elapsed = time.monotonic() - t0
                logger.error(f"VC not connected after {elapsed:.1f}s (is_connected=False)")
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
                return {"success": False, "error": "ボイスチャンネルへの接続がタイムアウトしました"}

            logger.info(f"VC connected in {time.monotonic() - t0:.1f}s")

        elif vc.channel.id != voice_channel.id:
            await vc.move_to(voice_channel)
            await asyncio.sleep(0.5)

        # Cancel idle timer
        state = self._state(guild_id)
        if state.idle_task:
            state.idle_task.cancel()
            state.idle_task = None

        # If already playing, add to queue
        if vc.is_playing() or vc.is_paused():
            gq = self.queue.get(guild_id)
            pos = gq.add(track)
            return {
                "success": True,
                "action": "queued",
                "track": self._track_dict(track),
                "position_in_queue": pos,
            }

        # Play immediately
        await self._start_playback(guild_id, vc, track)
        return {
            "success": True,
            "action": "playing",
            "track": self._track_dict(track),
            "position_in_queue": None,
        }

    async def stop(self, guild_id: str) -> dict:
        """Stop playback, clear queue, disconnect."""
        state = self._state(guild_id)
        vc = self._voice_client(guild_id)

        if state.idle_task:
            state.idle_task.cancel()
            state.idle_task = None

        self.queue.get(guild_id).clear()
        state.current_track = None
        state.start_time = None

        if vc and vc.is_connected():
            vc.stop()
            await vc.disconnect()

        return {"success": True}

    async def pause(self, guild_id: str) -> dict:
        vc = self._voice_client(guild_id)
        if not vc or not vc.is_playing():
            return {"success": False, "error": "再生中ではありません"}
        vc.pause()
        return {"success": True}

    async def resume(self, guild_id: str) -> dict:
        vc = self._voice_client(guild_id)
        if not vc or not vc.is_paused():
            return {"success": False, "error": "一時停止中ではありません"}
        vc.resume()
        return {"success": True}

    async def skip(self, guild_id: str) -> dict:
        vc = self._voice_client(guild_id)
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return {"success": False, "error": "再生中ではありません"}
        # Stop triggers the after callback, which plays next
        vc.stop()
        return {"success": True}

    async def set_volume(self, guild_id: str, volume: int) -> dict:
        volume = max(0, min(100, volume))
        self.queue.get(guild_id).volume = volume

        vc = self._voice_client(guild_id)
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = volume / 100

        return {"success": True, "volume": volume}

    async def set_loop(self, guild_id: str, mode: str) -> dict:
        if mode not in ("off", "track", "queue"):
            return {"success": False, "error": f"無効なループモード: {mode}"}
        self.queue.get(guild_id).loop_mode = mode
        return {"success": True, "loop_mode": mode}

    async def toggle_shuffle(self, guild_id: str) -> dict:
        gq = self.queue.get(guild_id)
        gq.shuffle = not gq.shuffle
        return {"success": True, "shuffle": gq.shuffle}

    def get_status(self, guild_id: str) -> dict:
        state = self._state(guild_id)
        vc = self._voice_client(guild_id)
        gq = self.queue.get(guild_id)

        connected = vc is not None and vc.is_connected()
        playing = connected and (vc.is_playing() or vc.is_paused())

        result = {
            "connected": connected,
            "channel_id": str(vc.channel.id) if connected else None,
            "channel_name": vc.channel.name if connected else None,
            "playing": vc.is_playing() if connected else False,
            "paused": vc.is_paused() if connected else False,
            "current_track": None,
            "queue_length": len(gq.tracks),
            "volume": gq.volume,
            "loop_mode": gq.loop_mode,
            "shuffle": gq.shuffle,
        }

        if playing and state.current_track:
            elapsed = 0
            if state.start_time:
                elapsed = int((datetime.now() - state.start_time).total_seconds())
            result["current_track"] = {
                **self._track_dict(state.current_track),
                "elapsed_seconds": elapsed,
            }

        return result

    async def _start_playback(
        self, guild_id: str, vc: discord.VoiceClient, track: Track
    ) -> None:
        state = self._state(guild_id)
        gq = self.queue.get(guild_id)

        # Refresh stream URL if empty
        if not track.stream_url:
            fresh_url = await self.extractor.refresh_stream_url(track.url)
            if not fresh_url:
                logger.error(f"Cannot get stream URL for {track.url}")
                await self._play_next(guild_id)
                return
            track.stream_url = fresh_url

        state.current_track = track
        state.start_time = datetime.now()

        # Verify connection before playing
        if not vc.is_connected():
            logger.error(f"Voice client not connected when trying to play in guild {guild_id}")
            state.current_track = None
            state.start_time = None
            return

        source = discord.FFmpegPCMAudio(
            track.stream_url,
            before_options=FFMPEG_BEFORE,
            options=FFMPEG_OPTIONS,
        )
        source = discord.PCMVolumeTransformer(source, volume=gq.volume / 100)

        def after(error):
            if error:
                logger.error(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_next(guild_id), self.bot.loop
            )

        try:
            vc.play(source, after=after)
        except Exception as e:
            logger.error(f"Failed to start playback: {e}")
            state.current_track = None
            state.start_time = None
            return
        logger.info(f"Playing: {track.title} - {track.artist} in guild {guild_id}")

    async def _play_next(self, guild_id: str) -> None:
        state = self._state(guild_id)
        vc = self._voice_client(guild_id)
        gq = self.queue.get(guild_id)

        if not vc or not vc.is_connected():
            state.current_track = None
            state.start_time = None
            return

        next_track = gq.next(state.current_track)
        if next_track:
            # Re-extract stream URL for next track (may have expired)
            fresh = await self.extractor.refresh_stream_url(next_track.url)
            if fresh:
                next_track.stream_url = fresh
            await self._start_playback(guild_id, vc, next_track)
        else:
            state.current_track = None
            state.start_time = None
            # Start idle timer
            state.idle_task = asyncio.create_task(
                self._idle_disconnect(guild_id)
            )

    async def _idle_disconnect(self, guild_id: str) -> None:
        """Disconnect after idle timeout."""
        try:
            await asyncio.sleep(self._config.idle_timeout)
            vc = self._voice_client(guild_id)
            if vc and vc.is_connected() and not vc.is_playing():
                logger.info(f"Idle timeout, disconnecting from guild {guild_id}")
                await vc.disconnect()
        except asyncio.CancelledError:
            pass

    async def _resolve_channel(
        self,
        guild: discord.Guild,
        channel_id: Optional[str],
        user_id: Optional[str],
    ) -> Optional[discord.VoiceChannel]:
        """Resolve target voice channel from channel_id or user's current channel."""
        if channel_id:
            ch = guild.get_channel(int(channel_id))
            if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                return ch

        if user_id:
            uid = int(user_id)

            # Method 1: member cache lookup
            member = guild.get_member(uid)
            if member and member.voice and member.voice.channel:
                logger.info(f"Resolved VC via member cache: {member.voice.channel.name}")
                return member.voice.channel

            # Method 2: scan voice channels directly (more reliable)
            for vc in guild.voice_channels + guild.stage_channels:
                for m in vc.members:
                    if m.id == uid:
                        logger.info(f"Resolved VC via channel scan: {vc.name}")
                        return vc

            # Method 3: fetch member from API (voice state comes from gateway cache)
            if not member:
                try:
                    member = await guild.fetch_member(uid)
                    if member and member.voice and member.voice.channel:
                        logger.info(f"Resolved VC via fetch_member: {member.voice.channel.name}")
                        return member.voice.channel
                except Exception as e:
                    logger.warning(f"fetch_member failed for {uid}: {e}")

            logger.warning(
                f"Could not resolve VC for user {user_id} in guild {guild.id}. "
                f"Member cached: {member is not None}, "
                f"Voice channels: {[f'{vc.name}({len(vc.members)} members)' for vc in guild.voice_channels]}"
            )

        return None

    def _track_dict(self, track: Track) -> dict:
        return {
            "title": track.title,
            "artist": track.artist,
            "url": track.url,
            "duration_seconds": track.duration_seconds,
            "thumbnail": track.thumbnail,
            "requester": track.requester,
            "source": track.source,
        }


# Global instance, initialized in main.py
voice_manager: Optional[VoiceManager] = None
