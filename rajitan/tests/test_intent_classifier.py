"""Tests for rajitan.nlp.intent_classifier module."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from rajitan.nlp.intent_classifier import (
    IntentType,
    IntentClassifier,
    ConfirmationGenerator,
    FunctionType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_response(content: str):
    """Create a mock OpenAI chat completion response."""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ---------------------------------------------------------------------------
# IntentClassifier.classify_intent
# ---------------------------------------------------------------------------

class TestIntentClassifier:
    @pytest.mark.asyncio
    async def test_classify_general_chat(self):
        response_json = json.dumps({"intent": "general_chat", "confidence": 0.95})
        mock_response = _make_openai_response(response_json)

        with patch("rajitan.nlp.intent_classifier.OpenAIClient") as MockOAI:
            instance = MockOAI.return_value
            instance.client = MagicMock()
            instance.client.chat.completions.create = AsyncMock(return_value=mock_response)
            instance.model = "gpt-4o-mini"

            classifier = IntentClassifier()
            result = await classifier.classify_intent("こんにちは")

        assert result["intent"] == "general_chat"
        assert result["confidence"] >= 0.9

    @pytest.mark.asyncio
    async def test_classify_schedule_request(self):
        response_json = json.dumps({
            "intent": "schedule_request",
            "confidence": 0.88,
            "schedule_info": {
                "schedule_type": "one_time",
                "function_type": "music",
                "time_info": "19:00",
                "additional_params": {},
            },
        })
        mock_response = _make_openai_response(response_json)

        with patch("rajitan.nlp.intent_classifier.OpenAIClient") as MockOAI:
            instance = MockOAI.return_value
            instance.client = MagicMock()
            instance.client.chat.completions.create = AsyncMock(return_value=mock_response)
            instance.model = "gpt-4o-mini"

            classifier = IntentClassifier()
            result = await classifier.classify_intent("19:00に音楽をおすすめして")

        assert result["intent"] == "schedule_request"
        assert "schedule_info" in result
        assert result["schedule_info"]["function_type"] == "music"

    @pytest.mark.asyncio
    async def test_classify_music_request(self):
        response_json = json.dumps({"intent": "music_request", "confidence": 0.92})
        mock_response = _make_openai_response(response_json)

        with patch("rajitan.nlp.intent_classifier.OpenAIClient") as MockOAI:
            instance = MockOAI.return_value
            instance.client = MagicMock()
            instance.client.chat.completions.create = AsyncMock(return_value=mock_response)
            instance.model = "gpt-4o-mini"

            classifier = IntentClassifier()
            result = await classifier.classify_intent("音楽をおすすめして")

        assert result["intent"] == "music_request"

    @pytest.mark.asyncio
    async def test_classify_returns_unknown_on_invalid_json(self):
        mock_response = _make_openai_response("this is not json")

        with patch("rajitan.nlp.intent_classifier.OpenAIClient") as MockOAI:
            instance = MockOAI.return_value
            instance.client = MagicMock()
            instance.client.chat.completions.create = AsyncMock(return_value=mock_response)
            instance.model = "gpt-4o-mini"

            classifier = IntentClassifier()
            result = await classifier.classify_intent("テスト入力")

        assert result["intent"] == IntentType.UNKNOWN
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_classify_returns_unknown_on_exception(self):
        with patch("rajitan.nlp.intent_classifier.OpenAIClient") as MockOAI:
            instance = MockOAI.return_value
            instance.client = MagicMock()
            instance.client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))
            instance.model = "gpt-4o-mini"

            classifier = IntentClassifier()
            result = await classifier.classify_intent("テスト入力")

        assert result["intent"] == IntentType.UNKNOWN
        assert result["confidence"] == 0.0


class TestIntentTypeValues:
    def test_all_intent_types_are_strings(self):
        for intent_type in IntentType:
            assert isinstance(intent_type.value, str)

    def test_expected_intent_types_exist(self):
        expected = {"schedule_request", "summary_request", "quiz_request", "music_request", "general_chat", "unknown"}
        actual = {e.value for e in IntentType}
        assert expected == actual


# ---------------------------------------------------------------------------
# ConfirmationGenerator
# ---------------------------------------------------------------------------

class TestConfirmationGenerator:
    def test_generate_daily_summary_confirmation(self):
        gen = ConfirmationGenerator()
        schedule_data = {
            "execution_time": {
                "type": "specific",
                "pattern": "daily",
                "hour": 19,
                "minute": 0,
            },
            "function_config": {
                "type": FunctionType.SUMMARY,
            },
        }
        msg = gen.generate_schedule_confirmation(schedule_data)
        assert "確認" in msg
        assert "19:00" in msg
        assert "要約" in msg

    def test_generate_relative_time_confirmation(self):
        gen = ConfirmationGenerator()
        schedule_data = {
            "execution_time": {
                "type": "relative",
                "pattern": "once",
                "relative_minutes": 30,
            },
            "function_config": {
                "type": FunctionType.MUSIC,
            },
        }
        msg = gen.generate_schedule_confirmation(schedule_data)
        assert "30分後" in msg
        assert "音楽" in msg

    def test_generate_weekly_quiz_confirmation(self):
        gen = ConfirmationGenerator()
        schedule_data = {
            "execution_time": {
                "type": "specific",
                "pattern": "weekly",
                "hour": 20,
                "minute": 0,
                "day_of_week": 4,  # Friday
            },
            "function_config": {
                "type": FunctionType.QUIZ,
            },
        }
        msg = gen.generate_schedule_confirmation(schedule_data)
        assert "金" in msg
        assert "クイズ" in msg

    def test_generate_custom_message_confirmation(self):
        gen = ConfirmationGenerator()
        schedule_data = {
            "execution_time": {
                "type": "specific",
                "pattern": "once",
                "hour": 18,
                "minute": 30,
            },
            "function_config": {
                "type": FunctionType.CUSTOM_MESSAGE,
                "custom_message": "お疲れさまです！",
            },
        }
        msg = gen.generate_schedule_confirmation(schedule_data)
        assert "お疲れさまです" in msg
