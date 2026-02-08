import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
from rajitan.character.personality import PersonalityType
from rajitan.utils.logger import get_logger
from rajitan.utils.validators import validate_system_prompt, validate_character_name, validate_interval

logger = get_logger("discord_commands")

# Personality descriptions for UI display
PERSONALITY_DESCRIPTIONS = {
    "default": "バランスの取れた標準パーソナリティ",
    "rajitan": "ノリと勢いのらじたん本人☆ テンポよくフランクに接する",
    "cheerful": "元気で明るく陽気な性格",
    "calm": "落ち着いていてリラックスした性格",
    "witty": "ユーモアたっぷりの切れ者",
    "professional": "丁寧でフォーマルな対応",
    "friendly": "親しみやすくフレンドリー",
    "sarcastic": "皮肉屋だけど愛嬌がある",
}


class PersonalitySelect(discord.ui.Select):
    """Dropdown select for personality type"""

    def __init__(self, bot):
        self.bot_ref = bot
        options = [
            discord.SelectOption(
                label=ptype.value,
                description=PERSONALITY_DESCRIPTIONS.get(ptype.value, ""),
                value=ptype.value,
            )
            for ptype in PersonalityType
        ]
        super().__init__(
            placeholder="パーソナリティを選択...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        guild_id = str(interaction.guild.id)

        success = await self.bot_ref.character_manager.update_character_personality(
            guild_id, selected
        )

        if success:
            embed = discord.Embed(
                title="パーソナリティ更新完了",
                description=f"パーソナリティを **{selected}** に変更しました！\n"
                            f"{PERSONALITY_DESCRIPTIONS.get(selected, '')}",
                color=discord.Color.green(),
            )
            # Add button for custom prompt
            view = CustomPromptView(self.bot_ref, guild_id)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(
                "パーソナリティの更新に失敗しました。", ephemeral=True
            )


class CustomPromptView(discord.ui.View):
    """View with button to open custom prompt modal"""

    def __init__(self, bot, guild_id: str):
        super().__init__(timeout=120)
        self.bot_ref = bot
        self.guild_id = guild_id

    @discord.ui.button(label="カスタムプロンプトを設定", style=discord.ButtonStyle.secondary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SystemPromptModal(self.bot_ref, self.guild_id)
        await interaction.response.send_modal(modal)


class SystemPromptModal(discord.ui.Modal, title="カスタムシステムプロンプト"):
    """Modal for entering custom system prompt"""

    prompt_input = discord.ui.TextInput(
        label="システムプロンプト",
        style=discord.TextStyle.long,
        placeholder="キャラクターの振る舞いを指示するプロンプトを入力...",
        min_length=10,
        max_length=2000,
        required=True,
    )

    def __init__(self, bot, guild_id: str):
        super().__init__()
        self.bot_ref = bot
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        prompt = self.prompt_input.value

        character = await self.bot_ref.character_manager.get_character(self.guild_id)
        if not character:
            await interaction.response.send_message("キャラクターが見つかりません。", ephemeral=True)
            return

        personality_type = "default"
        if character.personality_traits:
            personality_type = character.personality_traits.get("type", "default")

        success = await self.bot_ref.character_manager.update_character_personality(
            self.guild_id, personality_type, system_prompt=prompt
        )

        if success:
            await interaction.response.send_message(
                "カスタムプロンプトを設定しました！", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "プロンプトの設定に失敗しました。", ephemeral=True
            )


class PersonalityView(discord.ui.View):
    """View containing the personality select dropdown"""

    def __init__(self, bot):
        super().__init__(timeout=120)
        self.add_item(PersonalitySelect(bot))


class RajitanCommands(commands.Cog):
    """Discord slash commands for Rajitan"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="キャラクターの初期設定")
    @app_commands.describe(
        name="キャラクター名（デフォルト: らじたん）",
        personality="パーソナリティタイプ",
    )
    async def setup_character(
        self,
        interaction: discord.Interaction,
        name: Optional[str] = "らじたん",
        personality: Optional[Literal["default", "rajitan", "cheerful", "calm", "witty", "professional", "friendly", "sarcastic"]] = "default",
    ):
        """Setup character for the guild"""
        if interaction.guild is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            if not await self.bot.has_manage_permissions(interaction.user):
                await interaction.response.send_message(
                    "このコマンドを使用する権限がありません。", ephemeral=True
                )
                return

            if name and not validate_character_name(name):
                await interaction.response.send_message(
                    "無効なキャラクター名です。1-32文字で入力してください。", ephemeral=True
                )
                return

            await interaction.response.defer()

            success = await self.bot.character_manager.create_character(
                guild_id=str(interaction.guild.id),
                name=name,
                personality_type=personality,
            )

            if success:
                embed = await self.bot.create_embed(
                    title="キャラクターセットアップ完了",
                    description=f"**{name}** のセットアップが完了しました！\n\n"
                               f"**パーソナリティ:** {personality}\n"
                               f"**説明:** {PERSONALITY_DESCRIPTIONS.get(personality, '')}\n\n"
                               f"パーソナリティを変更するには `/personality` コマンドを使ってね！",
                    color=discord.Color.green(),
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("キャラクターの作成に失敗しました。もう一度お試しください。")

        except Exception as e:
            logger.error(f"Error in setup command: {e}")
            await interaction.followup.send("キャラクターのセットアップ中にエラーが発生しました。")

    @app_commands.command(name="personality", description="パーソナリティを変更")
    async def personality_command(self, interaction: discord.Interaction):
        """Change character personality with interactive dropdown"""
        if interaction.guild is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            # Check current character
            character_info = await self.bot.character_manager.get_character_info(
                str(interaction.guild.id)
            )

            if not character_info:
                await interaction.response.send_message(
                    "まだキャラクターが設定されていません。`/setup` で設定してね！",
                    ephemeral=True,
                )
                return

            current_type = character_info.get("personality_type", "default")
            embed = discord.Embed(
                title="パーソナリティ設定",
                description=f"現在のパーソナリティ: **{current_type}**\n"
                            f"下のメニューから新しいパーソナリティを選択してください。",
                color=discord.Color.purple(),
            )
            view = PersonalityView(self.bot)
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in personality command: {e}")
            await interaction.response.send_message(
                "パーソナリティ設定中にエラーが発生しました。"
            )

    @app_commands.command(name="music", description="音楽をおすすめ")
    async def music_command(self, interaction: discord.Interaction):
        """Get music recommendation based on conversation mood"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            await interaction.response.defer()

            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)

            # Get conversation data
            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=30
            )

            # Fallback to Discord channel history
            if not recent_messages:
                recent_messages = await self.bot.fetch_discord_history_as_messages(
                    interaction.channel, limit=30
                )

            if not recent_messages:
                await interaction.followup.send("音楽をおすすめするために、もう少し会話してね！")
                return

            if not self.bot.music_recommender:
                await interaction.followup.send("音楽推薦機能が設定されていません。")
                return

            recommendation = await self.bot.music_recommender.generate_recommendation(
                guild_id=guild_id,
                channel_id=channel_id,
                messages=recent_messages,
            )

            if recommendation:
                formatted = self.bot.music_recommender.format_recommendation_for_discord(recommendation)
                embed = await self.bot.create_embed(
                    title="音楽推薦",
                    description=formatted,
                    color=discord.Color.orange(),
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "今の雰囲気にぴったりの曲が見つからなかったみたい。また話してからね！"
                )

        except Exception as e:
            logger.error(f"Error in music command: {e}")
            await interaction.followup.send("音楽推薦中にエラーが発生しました。")

    @app_commands.command(name="schedules", description="スケジュール一覧の表示")
    async def schedules_command(self, interaction: discord.Interaction):
        """Show active schedules for this channel"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            await interaction.response.defer()

            channel_id = str(interaction.channel.id)
            schedules = await self.bot.enhanced_schedule_manager.get_channel_schedules(channel_id)

            if not schedules:
                await interaction.followup.send("このチャンネルにはスケジュールが設定されていません。")
                return

            embed = await self.bot.create_embed(
                title="スケジュール一覧",
                description=f"このチャンネルには {len(schedules)} 件のスケジュールがあります。",
                color=discord.Color.teal(),
            )

            # Map function type to Japanese
            func_type_names = {
                "summary": "要約",
                "quiz": "クイズ",
                "music": "音楽推薦",
                "custom_message": "カスタムメッセージ",
            }

            for i, schedule in enumerate(schedules[:10], 1):
                ft = schedule.function_type.value if hasattr(schedule.function_type, 'value') else str(schedule.function_type)
                func_name = func_type_names.get(ft, ft)
                status = "有効" if schedule.is_active else "無効"
                next_exec = schedule.next_execution.strftime("%Y/%m/%d %H:%M") if schedule.next_execution else "未定"
                pattern = schedule.pattern.value if hasattr(schedule.pattern, 'value') else str(schedule.pattern or "once")

                embed.add_field(
                    name=f"#{i} {func_name}",
                    value=f"パターン: {pattern}\n"
                          f"次回実行: {next_exec}\n"
                          f"状態: {status}",
                    inline=True,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in schedules command: {e}")
            await interaction.followup.send("スケジュール一覧の取得中にエラーが発生しました。")

    @app_commands.command(name="chat", description="プライベートチャット")
    @app_commands.describe(message="キャラクターに送るメッセージ")
    async def chat(self, interaction: discord.Interaction, message: str):
        """Private chat with character - only visible to you"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            await interaction.response.defer(ephemeral=True)

            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)

            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=30
            )

            await self.bot.conversation_tracker.track_message(
                channel_id=channel_id,
                user_id=str(interaction.user.id),
                username=interaction.user.display_name,
                content=f"[PRIVATE] {message}",
            )

            response = await self.bot.character_manager.generate_response(
                guild_id=guild_id,
                messages=recent_messages,
                user_message=message,
                context={"channel_id": channel_id, "private_chat": True},
            )

            if response:
                embed = discord.Embed(
                    title="💬 プライベートチャット",
                    description=f"**あなた:** {message}\n\n**返答:** {response}",
                    color=discord.Color.purple(),
                )
                embed.set_footer(text="このメッセージはあなただけに見えています")
                await interaction.followup.send(embed=embed, ephemeral=True)

                await self.bot.conversation_tracker.track_message(
                    channel_id=channel_id,
                    user_id=str(self.bot.user.id) if self.bot.user else "bot",
                    username=self.bot.user.display_name if self.bot.user else "らじたん",
                    content=f"[PRIVATE] {response}",
                )
            else:
                await interaction.followup.send(
                    "返答を生成できませんでした。もう一度お試しください。", ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in chat command: {e}")
            await interaction.followup.send(
                "メッセージの処理中にエラーが発生しました。", ephemeral=True
            )

    @app_commands.command(name="summary", description="会話の要約を生成")
    async def manual_summary(self, interaction: discord.Interaction):
        """Manually trigger conversation summary"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            await interaction.response.defer()

            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)

            summary_data = await self.bot.conversation_tracker.get_conversation_summary_data(channel_id)

            messages = summary_data["messages"] if summary_data and summary_data.get("messages") else None
            if not messages:
                messages = await self.bot.fetch_discord_history_as_messages(
                    interaction.channel, limit=50
                )

            if not messages:
                await interaction.followup.send("要約する会話が見つかりません。")
                return

            summary = await self.bot.conversation_summarizer.generate_summary(
                guild_id=guild_id,
                channel_id=channel_id,
                messages=messages,
            )

            if summary:
                formatted_summary = await self.bot.conversation_summarizer.format_summary_for_discord(summary)
                embed = await self.bot.create_embed(
                    title="会話の要約",
                    description=formatted_summary,
                    color=discord.Color.blue(),
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("要約の生成に失敗しました。もう一度お試しください。")

        except Exception as e:
            logger.error(f"Error in summary command: {e}")
            await interaction.followup.send("要約の生成中にエラーが発生しました。")

    @app_commands.command(name="quiz", description="会話ベースのクイズを開始")
    async def start_quiz(self, interaction: discord.Interaction):
        """Start a quiz based on conversation"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            await interaction.response.defer()

            guild_id = str(interaction.guild.id)
            channel_id = str(interaction.channel.id)

            if await self.bot.quiz_runner.is_quiz_active(channel_id):
                await interaction.followup.send("このチャンネルではすでにクイズが進行中です。")
                return

            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=60
            )

            if len(recent_messages) < 5:
                recent_messages = await self.bot.fetch_discord_history_as_messages(
                    interaction.channel, limit=50
                )

            if len(recent_messages) < 5:
                await interaction.followup.send(
                    "クイズを生成するための会話データが不足しています。最低5件のメッセージが必要です。"
                )
                return

            quiz = await self.bot.quiz_generator.generate_quiz(
                guild_id=guild_id,
                channel_id=channel_id,
                messages=recent_messages,
            )

            if not quiz:
                await interaction.followup.send("クイズの生成に失敗しました。もう一度お試しください。")
                return

            success = await self.bot.quiz_runner.start_quiz(channel_id, quiz)

            if success:
                question_info = await self.bot.quiz_runner.get_current_question(channel_id)
                if question_info:
                    question_text = self.bot.quiz_generator.format_question_for_discord(
                        question_info["question"],
                        question_info["question_number"],
                        question_info["total_questions"],
                    )
                    embed = await self.bot.create_embed(
                        title="クイズ",
                        description=question_text,
                        color=discord.Color.gold(),
                    )
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send("クイズの開始に失敗しました。")
            else:
                await interaction.followup.send("クイズの開始に失敗しました。")

        except Exception as e:
            logger.error(f"Error in quiz command: {e}")
            await interaction.followup.send("クイズの開始中にエラーが発生しました。")

    @app_commands.command(name="status", description="ボットのステータス表示")
    async def status_command(self, interaction: discord.Interaction):
        """Show bot status"""
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            await interaction.response.defer()

            stats = self.bot.get_bot_stats()

            character_info = await self.bot.character_manager.get_character_info(
                str(interaction.guild.id)
            )

            conversation_stats = await self.bot.conversation_tracker.get_conversation_stats(
                str(interaction.channel.id)
            )

            embed = await self.bot.create_embed(
                title="ボットステータス",
                description="現在のボットの状態です。",
                color=discord.Color.blue(),
            )

            uptime_hours = round(stats["uptime"] / 3600, 1)
            embed.add_field(
                name="稼働情報",
                value=f"稼働時間: {uptime_hours} 時間\n"
                      f"レイテンシ: {stats['latency']}ms\n"
                      f"サーバー数: {stats['guilds']}",
                inline=True,
            )

            if character_info:
                embed.add_field(
                    name="キャラクター",
                    value=f"名前: {character_info['name']}\n"
                          f"性格: {character_info['personality_type']}\n"
                          f"作成日: {character_info['created_at'].strftime('%Y/%m/%d')}",
                    inline=True,
                )

            embed.add_field(
                name="会話統計",
                value=f"アクティブ: {'はい' if conversation_stats['is_active'] else 'いいえ'}\n"
                      f"メッセージ数: {conversation_stats['message_count']}\n"
                      f"参加者数: {conversation_stats['participant_count']}",
                inline=True,
            )

            # Agent system info
            if self.bot.agent_orchestrator:
                orch = self.bot.agent_orchestrator
                llm_model = orch.llm.model
                # Detect provider from base_url
                base_url = str(getattr(orch.llm.client, "base_url", ""))
                if "deepseek" in base_url:
                    provider = "DeepSeek"
                else:
                    provider = "OpenAI"
                tool_count = len(orch.tools)
                embed.add_field(
                    name="エージェント",
                    value=f"LLM: {provider} ({llm_model})\n"
                          f"ツール数: {tool_count}\n"
                          f"最大ステップ: {orch.MAX_STEPS}",
                    inline=True,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in status command: {e}")
            try:
                await interaction.followup.send("ステータスの取得中にエラーが発生しました。")
            except Exception:
                pass

    @app_commands.command(name="help", description="ヘルプ情報の表示")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information"""
        try:
            embed = await self.bot.create_embed(
                title="ヘルプ",
                description="らじたんの使い方です。",
                color=discord.Color.green(),
            )

            embed.add_field(
                name="基本コマンド",
                value="`/setup` - キャラクターの初期設定\n"
                      "`/personality` - パーソナリティの変更（ドロップダウン）\n"
                      "`/status` - ボットのステータス表示\n"
                      "`/help` - このヘルプを表示",
                inline=False,
            )

            embed.add_field(
                name="会話機能",
                value="`/chat` - プライベートチャット（自分だけに見える）\n"
                      "`/summary` - 会話の要約を生成\n"
                      "`/quiz` - 会話ベースのクイズを開始\n"
                      "`/music` - 会話の雰囲気に合った音楽をおすすめ",
                inline=False,
            )

            embed.add_field(
                name="スケジュール",
                value="`/schedules` - スケジュール一覧の表示\n"
                      "`@らじたん 19:00に要約して` - メンションでスケジュール設定",
                inline=False,
            )

            embed.add_field(
                name="メンション機能",
                value="`@らじたん こんにちは` - 通常チャット\n"
                      "`@らじたん 要約して` - 会話を要約\n"
                      "`@らじたん クイズ出して` - クイズを開始\n"
                      "`@らじたん 音楽おすすめして` - 音楽を推薦",
                inline=False,
            )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await interaction.response.send_message("ヘルプの表示中にエラーが発生しました。")


async def setup(bot):
    """Setup commands cog"""
    await bot.add_cog(RajitanCommands(bot))
