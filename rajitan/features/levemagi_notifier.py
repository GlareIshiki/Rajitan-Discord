import math
import discord
from rajitan.utils.logger import get_logger

logger = get_logger("levemagi_notifier")


def calculate_level(total_xp: float) -> int:
    """Calculate level from total XP: level = floor(sqrt(total_xp / 100))"""
    if total_xp <= 0:
        return 0
    return math.floor(math.sqrt(total_xp / 100))


def xp_for_next_level(current_level: int) -> float:
    """Calculate XP needed to reach the next level"""
    next_level = current_level + 1
    return (next_level ** 2) * 100


class LeveMagiNotifier:
    """Sends Discord notifications for LeveMagi events in Rajitan's tone"""

    def __init__(self, bot):
        self.bot = bot

    async def notify_xp_gain(
        self,
        channel,
        user_id: str,
        xp_gained: float,
        total_xp: float,
    ):
        """Send XP gain notification with level info"""
        try:
            level = calculate_level(total_xp)
            next_level_xp = xp_for_next_level(level)
            remaining_xp = next_level_xp - total_xp

            description = (
                f"<@{user_id}> が **+{xp_gained:.1f} XP** ゲットしたよ!\n\n"
                f"現在のXP: **{total_xp:.1f}** XP\n"
                f"レベル: **Lv.{level}**\n"
            )

            if remaining_xp > 0:
                description += f"次のレベルまで: あと **{remaining_xp:.1f}** XP"
            else:
                description += "次のレベルまで: もうすぐ!"

            embed = discord.Embed(
                title="XP獲得! ☆",
                description=description,
                color=discord.Color.gold(),
            )

            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to send XP gain notification: {e}")

    async def notify_level_up(
        self,
        channel,
        user_id: str,
        new_level: int,
    ):
        """Send level up notification"""
        try:
            messages = [
                f"やった～!! <@{user_id}> が **Lv.{new_level}** にレベルアップしたよ!",
                "おめでと～! この調子でどんどんいこ～!!",
            ]

            # Special messages for milestone levels
            if new_level % 10 == 0:
                messages.append(f"Lv.{new_level} 到達は本当にすごいね! 尊敬しちゃう☆")
            elif new_level % 5 == 0:
                messages.append("キリ番レベルだね! 記念スクショしとく?♪")

            description = "\n".join(messages)

            embed = discord.Embed(
                title=f"LEVEL UP! Lv.{new_level} ☆",
                description=description,
                color=discord.Color.purple(),
            )

            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to send level up notification: {e}")

    async def notify_project_complete(
        self,
        channel,
        user_id: str,
        project_name: str,
    ):
        """Send project completion notification"""
        try:
            description = (
                f"<@{user_id}> がプロジェクト「**{project_name}**」を完了したよ!\n\n"
                f"お疲れさま～! 最後までやり遂げるの、ほんとカッコいい☆\n"
                f"次のプロジェクトも一緒にがんばろ～♪"
            )

            embed = discord.Embed(
                title="プロジェクト完了! ☆",
                description=description,
                color=discord.Color.green(),
            )

            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to send project completion notification: {e}")

    async def notify_task_complete(
        self,
        channel,
        user_id: str,
        task_title: str,
        xp_gained: float,
    ):
        """Send task completion notification with XP gain"""
        try:
            description = (
                f"<@{user_id}> がタスク「**{task_title}**」を完了!\n"
                f"**+{xp_gained:.1f} XP** ゲット♪ いいぞいいぞ～!"
            )

            embed = discord.Embed(
                title="タスク完了! ♪",
                description=description,
                color=discord.Color.teal(),
            )

            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to send task completion notification: {e}")

    async def notify_deadline_reminder(
        self,
        channel,
        user_id: str,
        project_name: str,
        deadline: str,
        hours_remaining: float,
    ):
        """Send deadline reminder notification"""
        try:
            if hours_remaining <= 0:
                urgency = "締切過ぎちゃってるよ!? 急いで!"
                color = discord.Color.red()
            elif hours_remaining <= 6:
                urgency = "あと数時間だよ! ラストスパート!"
                color = discord.Color.red()
            elif hours_remaining <= 24:
                urgency = "明日までだよ! がんばって!"
                color = discord.Color.orange()
            else:
                urgency = "そろそろ意識しとこ～"
                color = discord.Color.yellow()

            description = (
                f"<@{user_id}>\n"
                f"プロジェクト「**{project_name}**」の締切が近づいてるよ!\n\n"
                f"締切: **{deadline}**\n"
                f"{urgency}"
            )

            embed = discord.Embed(
                title="締切リマインダー",
                description=description,
                color=color,
            )

            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to send deadline reminder: {e}")
