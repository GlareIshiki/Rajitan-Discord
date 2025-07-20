from typing import Dict, Any, Optional
from enum import Enum
from rajitan.character.prompts import PERSONALITY_TRAITS


class PersonalityType(str, Enum):
    """Personality types for characters"""
    DEFAULT = "default"
    CHEERFUL = "cheerful"
    CALM = "calm"
    WITTY = "witty"
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    SARCASTIC = "sarcastic"


class PersonalityManager:
    """Manages character personality traits and behaviors"""
    
    def __init__(self):
        self.traits = PERSONALITY_TRAITS
    
    def get_personality_traits(self, personality_type: str) -> Dict[str, float]:
        """Get personality traits for a given type"""
        return self.traits.get(personality_type, self.traits["default"])
    
    def calculate_response_style(self, personality_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate response style based on personality and context"""
        traits = self.get_personality_traits(personality_type)
        
        # Base response style
        style = {
            "temperature": 0.7,
            "max_tokens": 300,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.6
        }
        
        # Adjust based on personality traits
        if traits["energy"] > 0.7:
            style["temperature"] = min(0.9, style["temperature"] + 0.2)
            style["max_tokens"] = min(400, style["max_tokens"] + 100)
        elif traits["energy"] < 0.4:
            style["temperature"] = max(0.5, style["temperature"] - 0.2)
            style["max_tokens"] = max(200, style["max_tokens"] - 100)
        
        if traits["humor"] > 0.8:
            style["temperature"] = min(0.9, style["temperature"] + 0.1)
            style["presence_penalty"] = max(0.3, style["presence_penalty"] - 0.2)
        
        if traits["formality"] > 0.6:
            style["temperature"] = max(0.5, style["temperature"] - 0.1)
            style["frequency_penalty"] = min(0.5, style["frequency_penalty"] + 0.1)
        
        # Adjust based on context
        conversation_mood = context.get("mood", "neutral")
        if conversation_mood == "excited":
            style["temperature"] = min(0.9, style["temperature"] + 0.1)
        elif conversation_mood == "serious":
            style["temperature"] = max(0.5, style["temperature"] - 0.1)
            style["formality"] = True
        
        return style
    
    def should_use_feature(self, personality_type: str, feature: str, context: Dict[str, Any]) -> bool:
        """Determine if a feature should be used based on personality"""
        traits = self.get_personality_traits(personality_type)
        
        if feature == "summary":
            # More helpful personalities are more likely to summarize
            base_probability = traits["helpfulness"] * 0.8
            
            # Adjust based on conversation length
            message_count = context.get("message_count", 0)
            if message_count > 20:
                base_probability += 0.2
            
            return base_probability > 0.6
        
        elif feature == "quiz":
            # More energetic and humorous personalities are more likely to do quiz
            base_probability = (traits["energy"] + traits["humor"]) / 2 * 0.7
            
            # Adjust based on conversation mood
            mood = context.get("mood", "neutral")
            if mood in ["excited", "positive"]:
                base_probability += 0.2
            elif mood in ["serious", "negative"]:
                base_probability -= 0.3
            
            return base_probability > 0.5
        
        elif feature == "music":
            # All personalities can recommend music, but style differs
            base_probability = 0.6
            
            # Adjust based on conversation mood
            mood = context.get("mood", "neutral")
            if mood != "neutral":
                base_probability += 0.2
            
            return base_probability > 0.5
        
        return False
    
    def get_feature_timing(self, personality_type: str, feature: str) -> int:
        """Get timing preference for features based on personality"""
        traits = self.get_personality_traits(personality_type)
        
        base_intervals = {
            "summary": 30,  # minutes
            "quiz": 60,     # minutes
            "music": 45     # minutes
        }
        
        base_interval = base_intervals.get(feature, 30)
        
        # High energy personalities act more frequently
        if traits["energy"] > 0.7:
            base_interval = int(base_interval * 0.8)
        elif traits["energy"] < 0.4:
            base_interval = int(base_interval * 1.3)
        
        # High helpfulness personalities summarize more often
        if feature == "summary" and traits["helpfulness"] > 0.8:
            base_interval = int(base_interval * 0.9)
        
        return max(5, base_interval)  # Minimum 5 minutes
    
    def customize_prompt_for_personality(self, base_prompt: str, personality_type: str) -> str:
        """Customize prompt based on personality type"""
        traits = self.get_personality_traits(personality_type)
        
        additions = []
        
        if traits["energy"] > 0.7:
            additions.append("元気で活発な性格で話してください。")
        elif traits["energy"] < 0.4:
            additions.append("落ち着いてリラックスした性格で話してください。")
        
        if traits["humor"] > 0.8:
            additions.append("時々ユーモアを交えて楽しい会話をしてください。")
        
        if traits["formality"] > 0.6:
            additions.append("丁寧で礼儀正しい言葉遣いで話してください。")
        elif traits["formality"] < 0.3:
            additions.append("カジュアルで親しみやすい言葉遣いで話してください。")
        
        if traits["friendliness"] > 0.8:
            additions.append("参加者みんなと親しみやすく接してください。")
        
        if additions:
            personality_instruction = "\n\n性格指定:\n" + "\n".join(additions)
            return base_prompt + personality_instruction
        
        return base_prompt