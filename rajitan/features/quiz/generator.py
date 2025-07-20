import asyncio
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from rajitan.storage.models import Message, Quiz
from rajitan.api.openai_client import OpenAIClient
from rajitan.character.manager import CharacterManager
from rajitan.utils.logger import get_logger

logger = get_logger("quiz_generator")


class QuizGenerator:
    """Generates quiz questions based on conversation content"""
    
    def __init__(self, openai_client: OpenAIClient, character_manager: CharacterManager):
        self.openai_client = openai_client
        self.character_manager = character_manager
    
    async def generate_quiz(
        self, 
        guild_id: str,
        channel_id: str,
        messages: List[Message],
        num_questions: int = 5
    ) -> Optional[Quiz]:
        """Generate quiz based on conversation messages"""
        try:
            if not messages:
                logger.warning("No messages to generate quiz from")
                return None
            
            # Get character for personalized quiz
            character = await self.character_manager.get_character(guild_id)
            character_name = character.name if character else "らじたん"
            
            # Generate quiz questions using OpenAI
            quiz_data = await self.openai_client.generate_quiz(messages, character_name)
            
            if not quiz_data:
                logger.error("Failed to generate quiz data")
                return None
            
            # Validate and limit questions
            valid_questions = []
            for question_data in quiz_data[:num_questions]:
                if self._validate_question(question_data):
                    valid_questions.append(question_data)
            
            if not valid_questions:
                logger.error("No valid questions generated")
                return None
            
            # Create quiz object
            quiz = Quiz(
                questions=valid_questions,
                channel_id=channel_id,
                created_at=datetime.now(),
                current_question=0,
                participants={},
                is_active=True
            )
            
            logger.info(f"Quiz generated for channel {channel_id}: {len(valid_questions)} questions")
            return quiz
            
        except Exception as e:
            logger.error(f"Failed to generate quiz: {e}")
            return None
    
    def _validate_question(self, question_data: Dict[str, Any]) -> bool:
        """Validate quiz question format"""
        try:
            required_fields = ["question", "options", "correct_answer", "explanation"]
            
            # Check all required fields exist
            for field in required_fields:
                if field not in question_data:
                    logger.warning(f"Missing field '{field}' in question")
                    return False
            
            # Validate question
            if not question_data["question"] or len(question_data["question"]) < 10:
                logger.warning("Question text too short")
                return False
            
            # Validate options (should be 4 choices)
            options = question_data["options"]
            if not isinstance(options, list) or len(options) != 4:
                logger.warning("Invalid options format")
                return False
            
            # Validate each option starts with A:, B:, C:, D:
            expected_prefixes = ["A:", "B:", "C:", "D:"]
            for i, option in enumerate(options):
                if not option.startswith(expected_prefixes[i]):
                    logger.warning(f"Option {i} doesn't start with correct prefix")
                    return False
            
            # Validate correct answer
            correct_answer = question_data["correct_answer"]
            if correct_answer not in ["A", "B", "C", "D"]:
                logger.warning("Invalid correct answer")
                return False
            
            # Validate explanation
            if not question_data["explanation"] or len(question_data["explanation"]) < 5:
                logger.warning("Explanation too short")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to validate question: {e}")
            return False
    
    async def should_generate_quiz(
        self, 
        guild_id: str,
        messages: List[Message], 
        context: Dict[str, Any]
    ) -> bool:
        """Determine if quiz should be generated based on character and context"""
        try:
            if not messages or len(messages) < 15:
                return False
            
            # Check character preference for quiz
            should_use = await self.character_manager.should_use_feature(
                guild_id, "quiz", context
            )
            
            if not should_use:
                return False
            
            # Additional checks
            activity_level = context.get("activity", {}).get("activity_level", "inactive")
            participant_count = context.get("activity", {}).get("participant_count", 0)
            sentiment = context.get("sentiment", "neutral")
            
            # Need active conversation with multiple participants
            if activity_level in ["inactive", "low"] or participant_count < 2:
                return False
            
            # Prefer positive/exciting conversations for quiz
            if sentiment in ["positive", "excited"]:
                return True
            
            # Random chance for neutral conversations if active enough
            if activity_level in ["medium", "high"] and participant_count >= 3:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check quiz generation need: {e}")
            return False
    
    async def get_quiz_timing(self, guild_id: str) -> int:
        """Get preferred timing for quiz based on character"""
        try:
            timing = await self.character_manager.get_feature_timing(guild_id, "quiz")
            return timing
            
        except Exception as e:
            logger.error(f"Failed to get quiz timing: {e}")
            return 60  # Default 60 minutes
    
    async def create_fallback_quiz(self, channel_id: str) -> Optional[Quiz]:
        """Create a fallback quiz with general questions"""
        try:
            fallback_questions = [
                {
                    "question": "日本で一番高い山は？",
                    "options": ["A: 富士山", "B: 北岳", "C: 白馬岳", "D: 阿蘇山"],
                    "correct_answer": "A",
                    "explanation": "富士山は標高3,776mで、日本一高い山です。"
                },
                {
                    "question": "Discordのサービス開始年は？",
                    "options": ["A: 2013年", "B: 2014年", "C: 2015年", "D: 2016年"],
                    "correct_answer": "C",
                    "explanation": "Discordは2015年にサービスを開始しました。"
                },
                {
                    "question": "プログラミング言語Pythonの名前の由来は？",
                    "options": ["A: 蛇のパイソン", "B: 英国のコメディグループ", "C: 古代ギリシャの神", "D: 数学の定理"],
                    "correct_answer": "B",
                    "explanation": "Pythonは英国のコメディグループ「モンティ・パイソン」から名付けられました。"
                }
            ]
            
            quiz = Quiz(
                questions=fallback_questions,
                channel_id=channel_id,
                created_at=datetime.now(),
                current_question=0,
                participants={},
                is_active=True
            )
            
            logger.info(f"Fallback quiz created for channel {channel_id}")
            return quiz
            
        except Exception as e:
            logger.error(f"Failed to create fallback quiz: {e}")
            return None
    
    def format_question_for_discord(self, question_data: Dict[str, Any], question_number: int, total_questions: int) -> str:
        """Format quiz question for Discord display"""
        try:
            formatted = f"🎤 **クイズ {question_number}/{total_questions}**\n\n"
            formatted += f"**{question_data['question']}**\n\n"
            
            for option in question_data['options']:
                formatted += f"{option}\n"
            
            formatted += "\n💬 答えはABCDのいずれかで答えてください。"
            
            return formatted
            
        except Exception as e:
            logger.error(f"Failed to format question: {e}")
            return "クイズの表示にエラーが発生しました。"
    
    def format_answer_for_discord(self, question_data: Dict[str, Any], is_correct: bool, user_answer: str) -> str:
        """Format quiz answer for Discord display"""
        try:
            if is_correct:
                formatted = "🎉 **正解です！**\n\n"
            else:
                formatted = f"❌ **不正解** 正解は **{question_data['correct_answer']}** でした\n\n"
            
            # Show correct answer
            correct_option = None
            for option in question_data['options']:
                if option.startswith(f"{question_data['correct_answer']}:"):
                    correct_option = option
                    break
            
            if correct_option:
                formatted += f"**正解:** {correct_option}\n\n"
            
            # Add explanation
            formatted += f"**解説:** {question_data['explanation']}"
            
            return formatted
            
        except Exception as e:
            logger.error(f"Failed to format answer: {e}")
            return "答えの表示にエラーが発生しました。"