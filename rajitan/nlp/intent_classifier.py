import asyncio
import json
from typing import Dict, Any, Optional, List
from enum import Enum
from rajitan.api.openai_client import OpenAIClient
from rajitan.utils.logger import get_logger

logger = get_logger("intent_classifier")


class IntentType(str, Enum):
    """Types of user intents"""
    SCHEDULE_REQUEST = "schedule_request"
    SUMMARY_REQUEST = "summary_request"
    QUIZ_REQUEST = "quiz_request"
    MUSIC_REQUEST = "music_request"
    GENERAL_CHAT = "general_chat"
    UNKNOWN = "unknown"


class ScheduleType(str, Enum):
    """Types of schedule requests"""
    PERIODIC = "periodic"
    ONE_TIME = "one_time"


class FunctionType(str, Enum):
    """Types of functions that can be scheduled"""
    SUMMARY = "summary"
    QUIZ = "quiz"
    MUSIC = "music"
    CUSTOM_MESSAGE = "custom_message"


class IntentClassifier:
    """Classifies user intents from natural language input"""
    
    def __init__(self):
        self.openai_client = OpenAIClient()
    
    async def classify_intent(self, user_input: str) -> Dict[str, Any]:
        """
        Classify user intent from natural language input
        
        Returns:
            Dict containing intent type and extracted information
        """
        try:
            # Create classification prompt
            classification_prompt = self._create_classification_prompt(user_input)
            
            # Get classification from OpenAI
            response = await self.openai_client.client.chat.completions.create(
                model=self.openai_client.model,
                messages=[
                    {"role": "system", "content": classification_prompt},
                    {"role": "user", "content": user_input}
                ],
                max_tokens=300,
                temperature=0.1
            )
            
            content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                result = json.loads(content)
                return self._validate_classification_result(result)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse classification JSON: {content}")
                return {"intent": IntentType.UNKNOWN, "confidence": 0.0}
                
        except Exception as e:
            logger.error(f"Failed to classify intent: {e}")
            return {"intent": IntentType.UNKNOWN, "confidence": 0.0}
    
    def _create_classification_prompt(self, user_input: str) -> str:
        """Create prompt for intent classification"""
        return f"""
あなたは自然言語処理の専門家です。ユーザーの入力を分析して、以下の意図のいずれかに分類してください：

1. schedule_request: スケジュール設定の依頼
   - 例: "19:00に音楽をおすすめして", "毎日18時に要約して", "30分後にクイズを出して"
   
2. summary_request: 会話要約の依頼
   - 例: "今日の会話を要約して", "ここまでの内容をまとめて", "会話の内容を教えて"
   
3. quiz_request: クイズ出題の依頼
   - 例: "クイズを出して", "問題を作って", "クイズゲームをしよう"
   
4. music_request: 音楽推薦の依頼
   - 例: "音楽をおすすめして", "曲を教えて", "BGMを提案して"
   
5. general_chat: 一般的な会話
   - 例: "こんにちは", "元気？", "今日はどう？"

スケジュール設定の場合は、追加で以下の情報も抽出してください：
- schedule_type: "periodic"（定期実行）または "one_time"（一回限り）
- function_type: "summary", "quiz", "music", "custom_message"
- time_info: 時間に関する情報
- additional_params: その他のパラメータ

JSON形式で以下のように返してください：
{{
  "intent": "intent_type",
  "confidence": 0.0-1.0,
  "schedule_info": {{
    "schedule_type": "periodic/one_time",
    "function_type": "summary/quiz/music/custom_message",
    "time_info": "時間情報",
    "additional_params": {{}}
  }}
}}

ユーザー入力: {user_input}
"""
    
    def _validate_classification_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize classification result"""
        try:
            # Ensure required fields exist
            intent = result.get("intent", IntentType.UNKNOWN)
            confidence = float(result.get("confidence", 0.0))
            
            # Validate intent type
            if intent not in [e.value for e in IntentType]:
                intent = IntentType.UNKNOWN
                confidence = 0.0
            
            validated_result = {
                "intent": intent,
                "confidence": confidence
            }
            
            # Add schedule info if present
            if "schedule_info" in result and intent == IntentType.SCHEDULE_REQUEST:
                schedule_info = result["schedule_info"]
                validated_result["schedule_info"] = {
                    "schedule_type": schedule_info.get("schedule_type", ScheduleType.ONE_TIME),
                    "function_type": schedule_info.get("function_type", FunctionType.CUSTOM_MESSAGE),
                    "time_info": schedule_info.get("time_info", ""),
                    "additional_params": schedule_info.get("additional_params", {})
                }
            
            return validated_result
            
        except Exception as e:
            logger.error(f"Failed to validate classification result: {e}")
            return {"intent": IntentType.UNKNOWN, "confidence": 0.0}


class ScheduleParser:
    """Parses schedule information from natural language"""
    
    def __init__(self):
        self.openai_client = OpenAIClient()
    
    async def parse_schedule_request(self, user_input: str, schedule_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse detailed schedule information from user input
        
        Args:
            user_input: Original user input
            schedule_info: Basic schedule info from intent classifier
            
        Returns:
            Detailed schedule information or None if parsing fails
        """
        try:
            # Create detailed parsing prompt
            parsing_prompt = self._create_parsing_prompt(user_input, schedule_info)
            
            response = await self.openai_client.client.chat.completions.create(
                model=self.openai_client.model,
                messages=[
                    {"role": "system", "content": parsing_prompt},
                    {"role": "user", "content": user_input}
                ],
                max_tokens=400,
                temperature=0.1
            )
            
            content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                result = json.loads(content)
                return self._validate_schedule_result(result)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse schedule JSON: {content}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to parse schedule request: {e}")
            return None
    
    def _create_parsing_prompt(self, user_input: str, schedule_info: Dict[str, Any]) -> str:
        """Create prompt for detailed schedule parsing"""
        return f"""
あなたはスケジュール設定の専門家です。ユーザーの入力から詳細なスケジュール情報を抽出してください。

基本情報:
- 機能タイプ: {schedule_info.get('function_type', 'unknown')}
- スケジュールタイプ: {schedule_info.get('schedule_type', 'unknown')}

以下の情報を抽出してください：

1. 実行時間:
   - 具体的な時刻（例: 19:00, 18時30分）
   - 相対時間（例: 30分後, 1時間後）
   - 定期パターン（例: 毎日, 毎週月曜日, 毎月1日）

2. 実行機能:
   - summary: 会話要約
   - quiz: クイズ出題
   - music: 音楽推薦
   - custom_message: カスタムメッセージ

3. 追加パラメータ:
   - カスタムメッセージの内容
   - 特定の日付や曜日
   - その他の設定

JSON形式で以下のように返してください：
{{
  "execution_time": {{
    "type": "specific/relative/periodic",
    "hour": 時,
    "minute": 分,
    "day_of_week": 曜日(0=月曜),
    "day_of_month": 日,
    "relative_minutes": 相対分数,
    "pattern": "hourly/daily/weekly/monthly/once"
  }},
  "function_config": {{
    "type": "summary/quiz/music/custom_message",
    "custom_message": "カスタムメッセージ",
    "parameters": {{}}
  }},
  "confirmation_needed": true/false,
  "parsed_successfully": true/false
}}

ユーザー入力: {user_input}
"""
    
    def _validate_schedule_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize schedule parsing result"""
        try:
            # Default values
            validated_result = {
                "execution_time": {
                    "type": "specific",
                    "hour": None,
                    "minute": None,
                    "day_of_week": None,
                    "day_of_month": None,
                    "relative_minutes": None,
                    "pattern": "once"
                },
                "function_config": {
                    "type": FunctionType.CUSTOM_MESSAGE,
                    "custom_message": "",
                    "parameters": {}
                },
                "confirmation_needed": True,
                "parsed_successfully": False
            }
            
            # Update with parsed values
            if "execution_time" in result:
                execution_time = result["execution_time"]
                validated_result["execution_time"].update({
                    k: v for k, v in execution_time.items() 
                    if k in validated_result["execution_time"]
                })
            
            if "function_config" in result:
                function_config = result["function_config"]
                validated_result["function_config"].update({
                    k: v for k, v in function_config.items() 
                    if k in validated_result["function_config"]
                })
            
            validated_result["confirmation_needed"] = result.get("confirmation_needed", True)
            validated_result["parsed_successfully"] = result.get("parsed_successfully", False)
            
            return validated_result
            
        except Exception as e:
            logger.error(f"Failed to validate schedule result: {e}")
            return {
                "execution_time": {"type": "specific", "pattern": "once"},
                "function_config": {"type": FunctionType.CUSTOM_MESSAGE},
                "confirmation_needed": True,
                "parsed_successfully": False
            }


class ConfirmationGenerator:
    """Generates confirmation messages for schedule settings"""
    
    def generate_schedule_confirmation(self, schedule_data: Dict[str, Any]) -> str:
        """Generate user-friendly confirmation message"""
        try:
            execution_time = schedule_data.get("execution_time", {})
            function_config = schedule_data.get("function_config", {})
            
            # Format time information
            time_str = self._format_time_info(execution_time)
            
            # Format function information
            function_str = self._format_function_info(function_config)
            
            # Generate confirmation message
            confirmation = f"確認だけど、{time_str}に{function_str}けど、いい？"
            
            return confirmation
            
        except Exception as e:
            logger.error(f"Failed to generate confirmation: {e}")
            return "スケジュール設定の確認に失敗しました。もう一度お試しください。"
    
    def _format_time_info(self, execution_time: Dict[str, Any]) -> str:
        """Format time information for confirmation"""
        time_type = execution_time.get("type", "specific")
        pattern = execution_time.get("pattern", "once")
        
        if pattern == "once":
            if time_type == "relative":
                minutes = execution_time.get("relative_minutes", 0)
                if minutes < 60:
                    return f"{minutes}分後"
                else:
                    hours = minutes // 60
                    return f"{hours}時間後"
            else:
                hour = execution_time.get("hour")
                minute = execution_time.get("minute", 0)
                if hour is not None:
                    return f"今日の{hour:02d}:{minute:02d}"
                else:
                    return "指定された時刻"
        
        elif pattern == "daily":
            hour = execution_time.get("hour", 0)
            minute = execution_time.get("minute", 0)
            return f"毎日{hour:02d}:{minute:02d}"
        
        elif pattern == "weekly":
            hour = execution_time.get("hour", 0)
            minute = execution_time.get("minute", 0)
            day_of_week = execution_time.get("day_of_week", 0)
            days = ["月", "火", "水", "木", "金", "土", "日"]
            day_name = days[day_of_week] if 0 <= day_of_week < 7 else "指定曜日"
            return f"毎週{day_name}曜日の{hour:02d}:{minute:02d}"
        
        elif pattern == "monthly":
            hour = execution_time.get("hour", 0)
            minute = execution_time.get("minute", 0)
            day_of_month = execution_time.get("day_of_month", 1)
            return f"毎月{day_of_month}日の{hour:02d}:{minute:02d}"
        
        else:
            return "指定された時刻"
    
    def _format_function_info(self, function_config: Dict[str, Any]) -> str:
        """Format function information for confirmation"""
        function_type = function_config.get("type", FunctionType.CUSTOM_MESSAGE)
        
        if function_type == FunctionType.SUMMARY:
            return "会話の要約をする"
        elif function_type == FunctionType.QUIZ:
            return "クイズを出題する"
        elif function_type == FunctionType.MUSIC:
            return "音楽をおすすめする"
        elif function_type == FunctionType.CUSTOM_MESSAGE:
            custom_message = function_config.get("custom_message", "")
            if custom_message:
                return f"「{custom_message}」を投稿する"
            else:
                return "メッセージを投稿する"
        else:
            return "指定された機能を実行する"