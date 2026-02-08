import discord
from discord import app_commands
from discord.ext import commands
from rajitan.utils.logger import get_logger

logger = get_logger("levemagi_commands")

# Priority display mapping
PRIORITY_ICONS = {
    "high": "!!!",
    "medium": "!!",
    "low": "!",
}


class LeveMagiCommands(commands.Cog):
    """LeveMagi slash commands for task/project management"""

    def __init__(self, bot):
        self.bot = bot

    def _get_levemagi_client(self):
        """Get the LeveMagi client from the bot, or None if unavailable"""
        client = getattr(self.bot, "levemagi_client", None)
        if client is None:
            logger.warning("LeveMagi client is not available")
        return client

    @app_commands.command(name="tasks", description="未完了タスク一覧")
    async def tasks_command(self, interaction: discord.Interaction):
        """Show user's incomplete tasks (Leaves where completed_at is None)"""
        try:
            await interaction.response.defer()

            client = self._get_levemagi_client()
            if client is None:
                await interaction.followup.send(
                    "LeveMagi機能が利用できません。管理者に連絡してください。"
                )
                return

            discord_id = str(interaction.user.id)

            # Ensure user exists
            await client.get_or_create_user(discord_id)

            # Get all leaves and filter incomplete ones
            all_leaves = await client.get_all_leaves(discord_id)
            incomplete_leaves = [
                leaf for leaf in all_leaves if leaf.completed_at is None
            ]

            if not incomplete_leaves:
                embed = await self.bot.create_embed(
                    title="未完了タスク",
                    description="未完了のタスクはないよ! やったね☆",
                    color=discord.Color.green(),
                )
                await interaction.followup.send(embed=embed)
                return

            # Get all nuts for project name lookup
            all_nuts = await client.get_all_nuts(discord_id)
            nuts_map = {nuts.id: nuts.name for nuts in all_nuts}

            embed = await self.bot.create_embed(
                title="未完了タスク一覧",
                description=f"全 {len(incomplete_leaves)} 件の未完了タスクがあるよ!",
                color=discord.Color.orange(),
            )

            for i, leaf in enumerate(incomplete_leaves[:25], 1):
                priority_icon = PRIORITY_ICONS.get(leaf.priority, "")
                project_name = nuts_map.get(leaf.nuts_id, "未分類") if leaf.nuts_id else "未分類"
                difficulty_str = f" [{leaf.difficulty}]" if leaf.difficulty else ""

                field_value = f"プロジェクト: {project_name}\n優先度: {leaf.priority} {priority_icon}{difficulty_str}"
                if leaf.memo:
                    field_value += f"\nメモ: {leaf.memo[:50]}"

                embed.add_field(
                    name=f"#{i} {leaf.title}",
                    value=field_value,
                    inline=True,
                )

            if len(incomplete_leaves) > 25:
                embed.set_footer(
                    text=f"他に {len(incomplete_leaves) - 25} 件のタスクがあります"
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in tasks command: {e}")
            try:
                await interaction.followup.send("タスク一覧の取得中にエラーが発生しました。")
            except Exception:
                pass

    @app_commands.command(name="projects", description="アクティブプロジェクト一覧")
    async def projects_command(self, interaction: discord.Interaction):
        """Show user's active projects (Nuts where status != '完了')"""
        try:
            await interaction.response.defer()

            client = self._get_levemagi_client()
            if client is None:
                await interaction.followup.send(
                    "LeveMagi機能が利用できません。管理者に連絡してください。"
                )
                return

            discord_id = str(interaction.user.id)

            # Ensure user exists
            await client.get_or_create_user(discord_id)

            # Get all nuts and filter active ones
            all_nuts = await client.get_all_nuts(discord_id)
            active_nuts = [
                nuts for nuts in all_nuts if nuts.status != "完了"
            ]

            if not active_nuts:
                embed = await self.bot.create_embed(
                    title="アクティブプロジェクト",
                    description="アクティブなプロジェクトはないよ! 新しいの始めちゃう?",
                    color=discord.Color.green(),
                )
                await interaction.followup.send(embed=embed)
                return

            embed = await self.bot.create_embed(
                title="アクティブプロジェクト一覧",
                description=f"全 {len(active_nuts)} 件のアクティブプロジェクトがあるよ!",
                color=discord.Color.blue(),
            )

            for i, nuts in enumerate(active_nuts[:25], 1):
                priority_icon = PRIORITY_ICONS.get(nuts.priority, "")
                deadline_str = f"\n締切: {nuts.deadline}" if nuts.deadline else ""
                tags_str = f"\nタグ: {', '.join(nuts.tags)}" if nuts.tags else ""

                field_value = (
                    f"ステータス: {nuts.status}\n"
                    f"優先度: {nuts.priority} {priority_icon}\n"
                    f"難易度: {nuts.difficulty}/10"
                    f"{deadline_str}{tags_str}"
                )

                embed.add_field(
                    name=f"#{i} {nuts.name}",
                    value=field_value,
                    inline=True,
                )

            if len(active_nuts) > 25:
                embed.set_footer(
                    text=f"他に {len(active_nuts) - 25} 件のプロジェクトがあります"
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in projects command: {e}")
            try:
                await interaction.followup.send("プロジェクト一覧の取得中にエラーが発生しました。")
            except Exception:
                pass


async def setup(bot):
    """Setup LeveMagi commands cog"""
    await bot.add_cog(LeveMagiCommands(bot))
