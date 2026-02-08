from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import math
import discord
from rajitan.utils.logger import get_logger
from rajitan.utils.decorators import handle_async_errors
from rajitan.storage.levemagi_models import LMLeafCreate

logger = get_logger("intent_strategy")


class IntentHandler(ABC):
    """Abstract base class for intent handlers"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @abstractmethod
    async def can_handle(self, intent: str, confidence: float) -> bool:
        """Check if this handler can process the given intent"""
        pass
    
    @abstractmethod
    async def handle(self, message: discord.Message, content: str, 
                    classification_result: Dict[str, Any]) -> bool:
        """Handle the intent and return True if successful"""
        pass


class SummaryRequestHandler(IntentHandler):
    """Handles summary requests"""
    
    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "summary_request" and confidence > 0.7
    
    @handle_async_errors(operation_name="handle summary request", default_return=False)
    async def handle(self, message: discord.Message, content: str, 
                    classification_result: Dict[str, Any]) -> bool:
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id)
        
        # Get conversation data
        summary_data = await self.bot.conversation_tracker.get_conversation_summary_data(channel_id)

        # Fallback to Discord channel history if no tracked data
        messages = summary_data["messages"] if summary_data and summary_data.get("messages") else None
        if not messages:
            messages = await self.bot.fetch_discord_history_as_messages(
                message.channel, limit=50
            )

        if not messages:
            await message.channel.send("最近の会話が見つからないよ。もう少し話してから要約を頼んでね！")
            return True

        # Generate summary
        summary = await self.bot.conversation_summarizer.generate_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=messages
        )
        
        if summary:
            # Format and send summary
            formatted_summary = await self.bot.conversation_summarizer.format_summary_for_discord(summary)
            intro_message = "OK♪ ここまでの内容を要約するね！\n\n"
            full_response = intro_message + formatted_summary
            
            # Track bot response
            try:
                await self.bot.conversation_tracker.track_message(
                    channel_id=channel_id,
                    user_id=str(self.bot.user.id) if self.bot.user else "bot",
                    username=self.bot.user.display_name if self.bot.user else "らじたん",
                    content=full_response
                )
            except Exception as e:
                logger.warning(f"Could not track bot response: {e}")
            
            await message.channel.send(full_response)
        else:
            await message.channel.send("要約の生成に失敗したよ。もう一度お試しください。")
        
        return True


class ScheduleRequestHandler(IntentHandler):
    """Handles schedule requests"""
    
    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "schedule_request" and confidence > 0.7
    
    @handle_async_errors(operation_name="handle schedule request", default_return=False)
    async def handle(self, message: discord.Message, content: str, 
                    classification_result: Dict[str, Any]) -> bool:
        from rajitan.nlp.intent_classifier import ScheduleParser, ConfirmationGenerator
        import asyncio
        
        schedule_info = classification_result.get("schedule_info", {})
        
        # Parse detailed schedule information
        schedule_parser = ScheduleParser()
        detailed_schedule = await schedule_parser.parse_schedule_request(content, schedule_info)
        
        if not detailed_schedule or not detailed_schedule.get("parsed_successfully"):
            await message.channel.send("スケジュール設定を理解できませんでした。もう一度詳しく教えてください。")
            return True
        
        # Generate confirmation message
        confirmation_generator = ConfirmationGenerator()
        confirmation_message = confirmation_generator.generate_schedule_confirmation(detailed_schedule)
        
        # Send confirmation with reactions
        confirmation_msg = await message.channel.send(confirmation_message)
        await confirmation_msg.add_reaction("✅")  # Yes
        await confirmation_msg.add_reaction("❌")  # No
        
        # Wait for user reaction
        def check(reaction, user):
            return (user == message.author and 
                   str(reaction.emoji) in ["✅", "❌"] and 
                   reaction.message.id == confirmation_msg.id)
        
        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            
            if str(reaction.emoji) == "✅":
                # User confirmed - create schedule
                success = await self.bot.create_schedule_from_parsed_data(
                    message, detailed_schedule
                )
                if success:
                    await message.channel.send("スケジュール設定完了！指定された時間に実行するね♪")
                else:
                    await message.channel.send("スケジュール設定に失敗しました。")
            else:
                # User rejected
                await message.channel.send("了解！スケジュール設定をキャンセルしたよ。")
                
        except asyncio.TimeoutError:
            await message.channel.send("時間切れです。スケジュール設定をキャンセルしました。")
        
        return True


class QuizRequestHandler(IntentHandler):
    """Handles quiz requests"""
    
    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "quiz_request" and confidence > 0.7
    
    @handle_async_errors(operation_name="handle quiz request", default_return=False)
    async def handle(self, message: discord.Message, content: str, 
                    classification_result: Dict[str, Any]) -> bool:
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id)
        
        # Check if quiz is already active
        if await self.bot.quiz_runner.is_quiz_active(channel_id):
            await message.channel.send("このチャンネルではすでにクイズが進行中だよ！")
            return True
        
        # Get conversation data
        recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
            channel_id, duration_minutes=60
        )

        # Fallback to Discord channel history if insufficient tracked data
        if len(recent_messages) < 5:
            recent_messages = await self.bot.fetch_discord_history_as_messages(
                message.channel, limit=50
            )

        if len(recent_messages) < 5:
            await message.channel.send("クイズを作るには、もう少し会話が必要だよ。もっと話してからお試しください！")
            return True
        
        # Generate and start quiz
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
                await message.channel.send(f"クイズタイム開始！♪\n\n{question_text}")
            else:
                await message.channel.send("クイズの開始に失敗しました。")
        else:
            await message.channel.send("クイズの生成に失敗しました。")
        
        return True


class MusicRequestHandler(IntentHandler):
    """Handles music recommendation requests"""
    
    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "music_request" and confidence > 0.7
    
    @handle_async_errors(operation_name="handle music request", default_return=False)
    async def handle(self, message: discord.Message, content: str,
                    classification_result: Dict[str, Any]) -> bool:
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id)

        # Get recent conversation for mood analysis
        recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
            channel_id, duration_minutes=30
        )

        # Fallback to Discord channel history
        if not recent_messages:
            recent_messages = await self.bot.fetch_discord_history_as_messages(
                message.channel, limit=30
            )

        if not recent_messages:
            await message.channel.send("音楽をおすすめするために、もう少し会話してね！")
            return True

        # Generate music recommendation
        if not self.bot.music_recommender:
            await message.channel.send("音楽推薦機能が設定されていないよ。")
            return True

        recommendation = await self.bot.music_recommender.generate_recommendation(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=recent_messages
        )

        if recommendation:
            formatted = self.bot.music_recommender.format_recommendation_for_discord(recommendation)
            await message.channel.send(f"現在の雰囲気に合った音楽をおすすめするね♪\n\n{formatted}")
        else:
            await message.channel.send("今の雰囲気にぴったりの曲が見つからなかったみたい。また話してからね！")

        return True


class TaskAddHandler(IntentHandler):
    """Handles task addition requests"""

    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "task_add" and confidence > 0.7

    @handle_async_errors(operation_name="handle task add", default_return=False)
    async def handle(self, message: discord.Message, content: str,
                    classification_result: Dict[str, Any]) -> bool:
        client = getattr(self.bot, "levemagi_client", None)
        if client is None:
            await message.channel.send("LeveMagi機能が利用できないよ。管理者に連絡してね！")
            return True

        discord_id = str(message.author.id)

        # Ensure user exists
        await client.get_or_create_user(discord_id)

        # Extract task title from message content
        # Remove common prefixes used when adding tasks
        task_title = content.strip()
        remove_prefixes = [
            "タスク追加", "タスクを追加", "タスク登録", "タスクを登録",
            "タスク作成", "タスクを作成", "タスクを追加して",
            "追加して", "登録して", "作成して",
            "やること追加", "やることを追加",
        ]
        for prefix in remove_prefixes:
            if task_title.startswith(prefix):
                task_title = task_title[len(prefix):].strip()
                # Remove particles that may remain
                if task_title.startswith(("：", ":", "、", " ")):
                    task_title = task_title[1:].strip()
                break

        if not task_title:
            await message.channel.send("タスク名を教えてね！例: 「タスク追加 レポートを書く」")
            return True

        # Create the leaf (task)
        leaf_data = LMLeafCreate(title=task_title)
        leaf = await client.create_leaf(discord_id, leaf_data)

        embed = discord.Embed(
            title="タスク追加完了 ♪",
            description=(
                f"タスク「**{leaf.title}**」を追加したよ！\n\n"
                f"ID: `{leaf.id}`\n"
                f"がんばってね☆"
            ),
            color=discord.Color.green(),
        )
        await message.channel.send(embed=embed)
        return True


class TaskCompleteHandler(IntentHandler):
    """Handles task completion requests"""

    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "task_complete" and confidence > 0.7

    @handle_async_errors(operation_name="handle task complete", default_return=False)
    async def handle(self, message: discord.Message, content: str,
                    classification_result: Dict[str, Any]) -> bool:
        client = getattr(self.bot, "levemagi_client", None)
        if client is None:
            await message.channel.send("LeveMagi機能が利用できないよ。管理者に連絡してね！")
            return True

        discord_id = str(message.author.id)

        # Ensure user exists
        user = await client.get_or_create_user(discord_id)

        # Get incomplete leaves
        all_leaves = await client.get_all_leaves(discord_id)
        incomplete_leaves = [leaf for leaf in all_leaves if leaf.completed_at is None]

        if not incomplete_leaves:
            await message.channel.send("未完了のタスクがないよ！すごいね☆")
            return True

        # Try to match task name from message content
        task_query = content.strip()
        remove_prefixes = [
            "タスク完了", "タスクを完了", "完了した", "完了にして",
            "終わった", "終わり", "できた", "やった",
            "タスク終了", "タスクを終了",
        ]
        for prefix in remove_prefixes:
            if task_query.startswith(prefix):
                task_query = task_query[len(prefix):].strip()
                if task_query.startswith(("：", ":", "、", " ")):
                    task_query = task_query[1:].strip()
                break

        matched_leaf = None

        if task_query:
            # Try exact match first
            for leaf in incomplete_leaves:
                if leaf.title == task_query:
                    matched_leaf = leaf
                    break

            # Try partial match
            if matched_leaf is None:
                matches = [
                    leaf for leaf in incomplete_leaves
                    if task_query.lower() in leaf.title.lower()
                ]
                if len(matches) == 1:
                    matched_leaf = matches[0]
                elif len(matches) > 1:
                    # Ambiguous - show options
                    lines = []
                    for i, leaf in enumerate(matches[:10], 1):
                        lines.append(f"**{i}.** {leaf.title}")
                    embed = discord.Embed(
                        title="どのタスクかな？",
                        description=(
                            "複数のタスクが見つかったよ！\n"
                            "タスク名をもう少し具体的に教えてね♪\n\n"
                            + "\n".join(lines)
                        ),
                        color=discord.Color.yellow(),
                    )
                    await message.channel.send(embed=embed)
                    return True

        # If no match found, show numbered list
        if matched_leaf is None:
            lines = []
            for i, leaf in enumerate(incomplete_leaves[:15], 1):
                lines.append(f"**{i}.** {leaf.title}")

            embed = discord.Embed(
                title="どのタスクを完了にする？",
                description=(
                    "完了にしたいタスク名を教えてね♪\n\n"
                    + "\n".join(lines)
                ),
                color=discord.Color.yellow(),
            )
            if len(incomplete_leaves) > 15:
                embed.set_footer(text=f"他にも {len(incomplete_leaves) - 15} 件あるよ")
            await message.channel.send(embed=embed)
            return True

        # Complete the matched leaf (default 0 actual_hours since not specified)
        completed_leaf = await client.complete_leaf(discord_id, matched_leaf.id, 0.0)

        if completed_leaf is None:
            await message.channel.send("タスクの完了処理に失敗したよ。もう一度試してね。")
            return True

        # Calculate XP: base 10 XP per task
        xp_gained = 10.0
        user = await client.add_xp(discord_id, xp_gained)

        # Check for level up
        old_level = math.floor(math.sqrt((user.total_xp - xp_gained) / 100)) if user.total_xp > xp_gained else 0
        new_level = math.floor(math.sqrt(user.total_xp / 100))

        embed = discord.Embed(
            title="タスク完了! ♪",
            description=(
                f"タスク「**{matched_leaf.title}**」を完了にしたよ！\n"
                f"**+{xp_gained:.0f} XP** ゲット☆\n\n"
                f"累計XP: **{user.total_xp:.0f}** XP (Lv.{new_level})"
            ),
            color=discord.Color.green(),
        )
        await message.channel.send(embed=embed)

        # Notify level up if applicable
        if new_level > old_level:
            try:
                from rajitan.features.levemagi_notifier import LeveMagiNotifier
                notifier = LeveMagiNotifier(self.bot)
                await notifier.notify_level_up(
                    message.channel, discord_id, new_level
                )
            except Exception as e:
                logger.warning(f"Could not send level up notification: {e}")

        return True


class TaskListHandler(IntentHandler):
    """Handles task list requests"""

    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "task_list" and confidence > 0.7

    @handle_async_errors(operation_name="handle task list", default_return=False)
    async def handle(self, message: discord.Message, content: str,
                    classification_result: Dict[str, Any]) -> bool:
        client = getattr(self.bot, "levemagi_client", None)
        if client is None:
            await message.channel.send("LeveMagi機能が利用できないよ。管理者に連絡してね！")
            return True

        discord_id = str(message.author.id)

        # Ensure user exists
        await client.get_or_create_user(discord_id)

        # Get all leaves and filter incomplete ones
        all_leaves = await client.get_all_leaves(discord_id)
        incomplete_leaves = [leaf for leaf in all_leaves if leaf.completed_at is None]

        if not incomplete_leaves:
            await message.channel.send("未完了のタスクはないよ！すっきり☆")
            return True

        # Get nuts for project name lookup
        all_nuts = await client.get_all_nuts(discord_id)
        nuts_map = {nuts.id: nuts.name for nuts in all_nuts}

        priority_icons = {"high": "!!!",  "medium": "!!", "low": "!"}

        lines = []
        for i, leaf in enumerate(incomplete_leaves[:15], 1):
            priority = priority_icons.get(leaf.priority, "")
            project = nuts_map.get(leaf.nuts_id, "") if leaf.nuts_id else ""
            project_str = f" ({project})" if project else ""
            lines.append(f"**{i}.** {leaf.title}{project_str} {priority}")

        embed = discord.Embed(
            title="未完了タスク一覧",
            description=(
                f"全 {len(incomplete_leaves)} 件あるよ！がんばろ～♪\n\n"
                + "\n".join(lines)
            ),
            color=discord.Color.orange(),
        )

        if len(incomplete_leaves) > 15:
            embed.set_footer(text=f"他にも {len(incomplete_leaves) - 15} 件あるよ")

        await message.channel.send(embed=embed)
        return True


class ProjectListHandler(IntentHandler):
    """Handles project list requests"""

    async def can_handle(self, intent: str, confidence: float) -> bool:
        return intent == "project_list" and confidence > 0.7

    @handle_async_errors(operation_name="handle project list", default_return=False)
    async def handle(self, message: discord.Message, content: str,
                    classification_result: Dict[str, Any]) -> bool:
        client = getattr(self.bot, "levemagi_client", None)
        if client is None:
            await message.channel.send("LeveMagi機能が利用できないよ。管理者に連絡してね！")
            return True

        discord_id = str(message.author.id)

        # Ensure user exists
        await client.get_or_create_user(discord_id)

        # Get all nuts and filter active ones
        all_nuts = await client.get_all_nuts(discord_id)
        active_nuts = [nuts for nuts in all_nuts if nuts.status != "完了"]

        if not active_nuts:
            await message.channel.send("アクティブなプロジェクトはないよ！新しいの始めちゃう？♪")
            return True

        lines = []
        for i, nuts in enumerate(active_nuts[:15], 1):
            deadline_str = f" (締切: {nuts.deadline})" if nuts.deadline else ""
            lines.append(f"**{i}.** {nuts.name} [{nuts.status}]{deadline_str}")

        embed = discord.Embed(
            title="アクティブプロジェクト一覧",
            description=(
                f"全 {len(active_nuts)} 件のプロジェクトがあるよ！\n\n"
                + "\n".join(lines)
            ),
            color=discord.Color.blue(),
        )

        if len(active_nuts) > 15:
            embed.set_footer(text=f"他にも {len(active_nuts) - 15} 件あるよ")

        await message.channel.send(embed=embed)
        return True


class GeneralChatHandler(IntentHandler):
    """Handles general chat interactions"""
    
    async def can_handle(self, intent: str, confidence: float) -> bool:
        return True  # This is the fallback handler
    
    @handle_async_errors(operation_name="handle general chat", default_return=False)
    async def handle(self, message: discord.Message, content: str, 
                    classification_result: Dict[str, Any]) -> bool:
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id)
        
        # Get recent conversation for context
        try:
            recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
                channel_id, duration_minutes=30
            )
        except Exception as e:
            logger.warning(f"Could not get recent conversation: {e}")
            recent_messages = []
        
        # Get character information
        character = await self.bot.character_manager.get_character(guild_id)
        
        if character:
            # Generate character response
            response = await self.bot.character_manager.generate_response(
                guild_id=guild_id,
                messages=recent_messages,
                user_message=content
            )
            
            if response:
                # Track bot response
                try:
                    await self.bot.conversation_tracker.track_message(
                        channel_id=channel_id,
                        user_id=str(self.bot.user.id) if self.bot.user else "bot",
                        username=self.bot.user.display_name if self.bot.user else "らじたん",
                        content=response
                    )
                except Exception as e:
                    logger.warning(f"Could not track bot response: {e}")
                
                await message.channel.send(response)
            else:
                # Fallback response
                await message.channel.send("ごめん、今ちょっと考えがまとまらないよ。もう一度話しかけてね！")
        else:
            # No character configured
            await message.channel.send("まだキャラクター設定が完了していないよ。管理者に設定をお願いしてね！")
        
        return True


class IntentRouter:
    """Routes intents to appropriate handlers"""
    
    def __init__(self, bot):
        self.bot = bot
        self.handlers = [
            SummaryRequestHandler(bot),
            ScheduleRequestHandler(bot),
            QuizRequestHandler(bot),
            MusicRequestHandler(bot),
            TaskAddHandler(bot),
            TaskCompleteHandler(bot),
            TaskListHandler(bot),
            ProjectListHandler(bot),
            GeneralChatHandler(bot)  # Keep this last as fallback
        ]
    
    @handle_async_errors(operation_name="route intent", default_return=False)
    async def route(self, message: discord.Message, content: str, 
                   classification_result: Dict[str, Any]) -> bool:
        """Route the intent to the appropriate handler"""
        intent = classification_result.get("intent")
        confidence = classification_result.get("confidence", 0.0)
        
        logger.info(f"Routing intent: {intent} (confidence: {confidence})")
        
        for handler in self.handlers:
            if await handler.can_handle(intent, confidence):
                logger.debug(f"Using handler: {handler.__class__.__name__}")
                return await handler.handle(message, content, classification_result)
        
        # This should not happen since GeneralChatHandler accepts everything
        logger.error("No handler found for intent")
        return False