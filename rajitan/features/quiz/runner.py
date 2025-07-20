import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from rajitan.storage.models import Quiz
from rajitan.storage.redis_client import RedisClient
from rajitan.utils.logger import get_logger

logger = get_logger("quiz_runner")


class QuizRunner:
    """Manages quiz execution and participant interaction"""
    
    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client
        self.active_quizzes: Dict[str, Quiz] = {}
        self.answer_timeout = 30  # seconds
    
    async def start_quiz(self, channel_id: str, quiz: Quiz) -> bool:
        """Start a quiz in a channel"""
        try:
            # Check if quiz is already running
            if channel_id in self.active_quizzes:
                logger.warning(f"Quiz already active in channel {channel_id}")
                return False
            
            # Store quiz
            self.active_quizzes[channel_id] = quiz
            
            # Store in Redis for persistence
            await self.redis_client.set_cache(
                f"active_quiz:{channel_id}", 
                quiz.dict(), 
                ttl=3600  # 1 hour
            )
            
            logger.info(f"Quiz started in channel {channel_id} with {len(quiz.questions)} questions")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start quiz: {e}")
            return False
    
    async def stop_quiz(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Stop a quiz and return final results"""
        try:
            quiz = await self.get_active_quiz(channel_id)
            if not quiz:
                return None
            
            # Calculate final results
            results = self._calculate_final_results(quiz)
            
            # Clean up
            if channel_id in self.active_quizzes:
                del self.active_quizzes[channel_id]
            
            await self.redis_client.delete_cache(f"active_quiz:{channel_id}")
            
            logger.info(f"Quiz stopped in channel {channel_id}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to stop quiz: {e}")
            return None
    
    async def get_active_quiz(self, channel_id: str) -> Optional[Quiz]:
        """Get active quiz for a channel"""
        try:
            # Check memory first
            if channel_id in self.active_quizzes:
                return self.active_quizzes[channel_id]
            
            # Check Redis
            quiz_data = await self.redis_client.get_cache(f"active_quiz:{channel_id}")
            if quiz_data:
                quiz = Quiz(**quiz_data)
                self.active_quizzes[channel_id] = quiz
                return quiz
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get active quiz: {e}")
            return None
    
    async def submit_answer(
        self, 
        channel_id: str, 
        user_id: str, 
        username: str,
        answer: str
    ) -> Optional[Dict[str, Any]]:
        """Submit an answer to the current quiz question"""
        try:
            quiz = await self.get_active_quiz(channel_id)
            if not quiz or not quiz.is_active:
                return None
            
            # Validate answer format
            answer = answer.upper().strip()
            if answer not in ["A", "B", "C", "D"]:
                return {"error": "答えはABCDのいずれかで入力してください。"}
            
            # Check if quiz is finished
            if quiz.current_question >= len(quiz.questions):
                return {"error": "クイズはすでに終了しています。"}
            
            # Get current question
            current_question = quiz.questions[quiz.current_question]
            correct_answer = current_question["correct_answer"]
            
            # Check if user already answered this question
            participant_key = f"{user_id}_{quiz.current_question}"
            if participant_key in quiz.participants:
                return {"error": "この問題にはすでに答えています。"}
            
            # Calculate score
            is_correct = answer == correct_answer
            score_increment = 1 if is_correct else 0
            
            # Update participant score
            if user_id not in quiz.participants:
                quiz.participants[user_id] = 0
            quiz.participants[user_id] += score_increment
            
            # Mark this question as answered by this user
            quiz.participants[participant_key] = score_increment
            
            # Update quiz in memory and Redis
            self.active_quizzes[channel_id] = quiz
            await self.redis_client.set_cache(
                f"active_quiz:{channel_id}", 
                quiz.dict(), 
                ttl=3600
            )
            
            result = {
                "is_correct": is_correct,
                "correct_answer": correct_answer,
                "user_answer": answer,
                "question": current_question,
                "current_score": quiz.participants[user_id],
                "question_number": quiz.current_question + 1,
                "total_questions": len(quiz.questions)
            }
            
            logger.debug(f"Answer submitted by {username} in channel {channel_id}: {answer} ({'correct' if is_correct else 'incorrect'})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to submit answer: {e}")
            return {"error": "答えの処理中にエラーが発生しました。"}
    
    async def next_question(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Move to the next question"""
        try:
            quiz = await self.get_active_quiz(channel_id)
            if not quiz or not quiz.is_active:
                return None
            
            # Move to next question
            quiz.current_question += 1
            
            # Check if quiz is finished
            if quiz.current_question >= len(quiz.questions):
                quiz.is_active = False
                final_results = self._calculate_final_results(quiz)
                
                # Update quiz
                self.active_quizzes[channel_id] = quiz
                await self.redis_client.set_cache(
                    f"active_quiz:{channel_id}", 
                    quiz.dict(), 
                    ttl=3600
                )
                
                return {
                    "quiz_finished": True,
                    "final_results": final_results
                }
            
            # Get next question
            next_question = quiz.questions[quiz.current_question]
            
            # Update quiz
            self.active_quizzes[channel_id] = quiz
            await self.redis_client.set_cache(
                f"active_quiz:{channel_id}", 
                quiz.dict(), 
                ttl=3600
            )
            
            return {
                "quiz_finished": False,
                "question": next_question,
                "question_number": quiz.current_question + 1,
                "total_questions": len(quiz.questions)
            }
            
        except Exception as e:
            logger.error(f"Failed to move to next question: {e}")
            return None
    
    def _calculate_final_results(self, quiz: Quiz) -> Dict[str, Any]:
        """Calculate final quiz results"""
        try:
            # Filter out individual question answers
            participant_scores = {}
            for key, score in quiz.participants.items():
                if "_" not in key:  # This is a user's total score
                    participant_scores[key] = score
            
            if not participant_scores:
                return {
                    "participants": [],
                    "winner": None,
                    "total_questions": len(quiz.questions)
                }
            
            # Sort participants by score
            sorted_participants = sorted(
                participant_scores.items(), 
                key=lambda x: x[1], 
                reverse=True
            )
            
            # Prepare results
            results = []
            for i, (user_id, score) in enumerate(sorted_participants):
                results.append({
                    "rank": i + 1,
                    "user_id": user_id,
                    "score": score,
                    "percentage": round((score / len(quiz.questions)) * 100, 1)
                })
            
            # Determine winner(s)
            max_score = sorted_participants[0][1] if sorted_participants else 0
            winners = [user_id for user_id, score in sorted_participants if score == max_score]
            
            return {
                "participants": results,
                "winners": winners,
                "max_score": max_score,
                "total_questions": len(quiz.questions),
                "total_participants": len(participant_scores)
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate final results: {e}")
            return {"participants": [], "winners": [], "total_questions": len(quiz.questions)}
    
    async def get_current_question(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get the current question for a quiz"""
        try:
            quiz = await self.get_active_quiz(channel_id)
            if not quiz or not quiz.is_active:
                return None
            
            if quiz.current_question >= len(quiz.questions):
                return None
            
            current_question = quiz.questions[quiz.current_question]
            
            return {
                "question": current_question,
                "question_number": quiz.current_question + 1,
                "total_questions": len(quiz.questions)
            }
            
        except Exception as e:
            logger.error(f"Failed to get current question: {e}")
            return None
    
    async def get_leaderboard(self, channel_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get current leaderboard for active quiz"""
        try:
            quiz = await self.get_active_quiz(channel_id)
            if not quiz:
                return None
            
            # Filter participant scores
            participant_scores = {}
            for key, score in quiz.participants.items():
                if "_" not in key:  # This is a user's total score
                    participant_scores[key] = score
            
            if not participant_scores:
                return []
            
            # Sort by score
            sorted_participants = sorted(
                participant_scores.items(), 
                key=lambda x: x[1], 
                reverse=True
            )
            
            leaderboard = []
            for i, (user_id, score) in enumerate(sorted_participants):
                leaderboard.append({
                    "rank": i + 1,
                    "user_id": user_id,
                    "score": score,
                    "questions_answered": quiz.current_question
                })
            
            return leaderboard
            
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return None
    
    async def is_quiz_active(self, channel_id: str) -> bool:
        """Check if a quiz is active in the channel"""
        try:
            quiz = await self.get_active_quiz(channel_id)
            return quiz is not None and quiz.is_active
            
        except Exception as e:
            logger.error(f"Failed to check quiz status: {e}")
            return False