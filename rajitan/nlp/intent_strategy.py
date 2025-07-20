from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import discord
from rajitan.utils.logger import get_logger
from rajitan.utils.decorators import handle_async_errors

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
        
        if not summary_data or not summary_data.get("messages"):
            await message.channel.send("最近の会話が見つからないよ。もう少し話してから要約を頼んでね！")
            return True
        
        # Generate summary
        summary = await self.bot.conversation_summarizer.generate_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            messages=summary_data["messages"]
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
        
        if len(recent_messages) < 15:
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
        
        # Get recent conversation for mood analysis
        recent_messages = await self.bot.conversation_tracker.get_recent_conversation(
            channel_id, duration_minutes=30
        )
        
        if not recent_messages:
            await message.channel.send("音楽をおすすめするために、もう少し会話してね！")
            return True
        
        # Generate music recommendation
        # Note: This requires music recommendation implementation
        recommendation_text = "現在の雰囲気に合った音楽をおすすめするね♪\n（音楽推薦機能は開発中です）"
        await message.channel.send(recommendation_text)
        
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