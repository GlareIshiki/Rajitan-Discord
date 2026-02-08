import asyncio
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config
from rajitan.utils.decorators import handle_async_errors, with_retries
from rajitan.storage.models import Message

logger = get_logger("openai_client")
config = get_config()


class OpenAIClient:
    """OpenAI API client for conversation and content generation"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=config.openai_api_key)
        self.model = "gpt-4o-mini"
    
    @handle_async_errors(operation_name="generate character response", default_return=None)
    @with_retries(max_retries=2, delay=1.0)
    async def generate_character_response(
        self, 
        system_prompt: str, 
        messages: List[Message], 
        user_message: str,
        max_tokens: int = 500
    ) -> Optional[str]:
        """Generate character response based on conversation context"""
        # Build conversation context
        conversation_context = self._build_conversation_context(messages)
        
        # Prepare messages for OpenAI API
        openai_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"過去の会話:\n{conversation_context}\n\n新しいメッセージ: {user_message}"}
        ]
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            max_tokens=max_tokens,
            temperature=0.8,
            presence_penalty=0.6,
            frequency_penalty=0.3
        )
        
        return response.choices[0].message.content.strip()
    
    @handle_async_errors(operation_name="generate summary", default_return=None)
    @with_retries(max_retries=2, delay=1.0)
    async def generate_summary(
        self, 
        messages: List[Message], 
        character_name: str = "らじたん"
    ) -> Optional[str]:
        """Generate conversation summary"""
        if not messages:
            return None
        
        conversation_text = self._build_conversation_context(messages)
        
        system_prompt = f"""
あなたは{character_name}というDiscordサーバーのラジオDJキャラクターです。
会話の内容をラジオ番組の要領で要約してください。

要約の際は以下を意識してください：
- 会話の主要なトピックを整理
- 参加者の雰囲気や盛り上がり
- ラジオDJの視点で楽しく
- 聞き手が興味を持つような内容

会話の流れを大切にして、その会話の雰囲気や内容を自然に要約してください。
"""
        
        openai_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下の会話を要約してください：\n\n{conversation_text}"}
        ]
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            max_tokens=400,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
    
    @handle_async_errors(operation_name="generate quiz", default_return=None)
    @with_retries(max_retries=2, delay=1.0)
    async def generate_quiz(
        self, 
        messages: List[Message], 
        character_name: str = "らじたん"
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate quiz questions based on conversation"""
        if not messages:
            return None
        
        conversation_text = self._build_conversation_context(messages)
        
        system_prompt = f"""
あなたは{character_name}というDiscordサーバーのラジオDJキャラクターです。
会話の内容をもとにクイズ問題を作成してください。

作成する問題の条件：
- 会話の内容に関連する問題を5-10問作成
- 4択問題（A, B, C, D）
- 正解は1つ
- 解説は簡潔でわかりやすく
- 問題は聞き手が楽しめるもの

以下のJSON形式で回答してください：
[
  {{
    "question": "問題文",
    "options": ["A: 選択肢1", "B: 選択肢2", "C: 選択肢3", "D: 選択肢4"],
    "correct_answer": "A",
    "explanation": "解説"
  }}
]
"""
        
        openai_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下の会話をもとにクイズを作成してください：\n\n{conversation_text}"}
        ]
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            max_tokens=800,
            temperature=0.8
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parse JSON response
        import json
        try:
            quiz_data = json.loads(content)
            return quiz_data
        except json.JSONDecodeError:
            logger.error("Failed to parse quiz JSON response")
            return None
    
    @handle_async_errors(operation_name="generate music recommendation", default_return=None)
    @with_retries(max_retries=2, delay=1.0)
    async def generate_music_recommendation(
        self, 
        messages: List[Message], 
        character_name: str = "らじたん"
    ) -> Optional[Dict[str, str]]:
        """Generate music recommendation based on conversation mood"""
        if not messages:
            return None
        
        conversation_text = self._build_conversation_context(messages)
        
        system_prompt = f"""
あなたは{character_name}というDiscordサーバーのラジオDJキャラクターです。
会話の雰囲気に合わせて、その場にふさわしい音楽を推薦してください。

推薦する際の条件：
- 会話の雰囲気に合った音楽
- 具体的な楽曲名とアーティスト名
- 推薦理由を簡潔に
- ラジオDJの視点で楽しく

以下のJSON形式で回答してください：
{{
  "title": "楽曲名",
  "artist": "アーティスト名",
  "reason": "推薦理由（会話の雰囲気に合わせて）"
}}
"""
        
        openai_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下の会話の雰囲気に合う音楽を推薦してください：\n\n{conversation_text}"}
        ]
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            max_tokens=300,
            temperature=0.9
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parse JSON response
        import json
        try:
            music_data = json.loads(content)
            return music_data
        except json.JSONDecodeError:
            logger.error("Failed to parse music recommendation JSON response")
            return None
    
    def _build_conversation_context(self, messages: List[Message]) -> str:
        """Build conversation context from messages"""
        context_lines = []
        
        for message in messages[-20:]:  # Use last 20 messages
            timestamp = message.timestamp.strftime("%H:%M")
            context_lines.append(f"[{timestamp}] {message.username}: {message.content}")
        
        return "\n".join(context_lines)
    
    @handle_async_errors(operation_name="analyze conversation sentiment", default_return=None)
    @with_retries(max_retries=2, delay=1.0)
    async def analyze_conversation_sentiment(self, messages: List[Message]) -> Optional[str]:
        """Analyze conversation sentiment"""
        if not messages:
            return None
        
        conversation_text = self._build_conversation_context(messages)
        
        system_prompt = """
会話の感情を分析してください。
以下の選択肢から最も適切な感情を1つ選んで回答してください：
- positive: 楽しい、明るい雰囲気
- negative: 悲しい、落ち込んだ雰囲気
- neutral: 普通の雰囲気
- excited: 興奮した、盛り上がった雰囲気
- relaxed: 落ち着いた、リラックスした雰囲気
"""
        
        openai_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下の会話の感情を分析してください：\n\n{conversation_text}"}
        ]
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            max_tokens=50,
            temperature=0.3
        )
        
        return response.choices[0].message.content.strip().lower()