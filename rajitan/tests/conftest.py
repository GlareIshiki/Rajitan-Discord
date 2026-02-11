"""Shared pytest fixtures for Rajitan Discord bot tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from rajitan.storage.models import Character, Message, Conversation, ConversationState


# ---------------------------------------------------------------------------
# OpenAI client mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_openai_client():
    """Mock OpenAIClient that returns predefined responses."""
    client = MagicMock()

    client.generate_character_response = AsyncMock(
        return_value="こんにちは！今日も楽しくいこうね！"
    )
    client.generate_summary = AsyncMock(
        return_value="今日の会話はゲームの話題で盛り上がりました！"
    )
    client.generate_quiz = AsyncMock(
        return_value=[
            {
                "question": "テスト問題",
                "options": ["A: 選択肢1", "B: 選択肢2", "C: 選択肢3", "D: 選択肢4"],
                "correct_answer": "A",
                "explanation": "テスト解説",
            }
        ]
    )
    client.generate_music_recommendation = AsyncMock(
        return_value={
            "title": "Lemon",
            "artist": "米津玄師",
            "reason": "会話の穏やかな雰囲気にぴったりの楽曲です。",
        }
    )
    client.analyze_conversation_sentiment = AsyncMock(return_value="positive")

    # Provide a mock for the raw chat completions API used by IntentClassifier
    mock_choice = MagicMock()
    mock_choice.message.content = '{"intent": "general_chat", "confidence": 0.9}'
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_chat = MagicMock()
    mock_chat.completions.create = AsyncMock(return_value=mock_response)
    client.client = MagicMock()
    client.client.chat = mock_chat
    client.model = "gpt-4o-mini"

    return client


# ---------------------------------------------------------------------------
# Redis client mock (in-memory fallback mode)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis_client():
    """Mock RedisClient using the in-memory fallback mode."""
    client = MagicMock()
    client._use_fallback = True
    client._memory_cache = {}
    client._initialized = True

    client.initialize = AsyncMock()
    client.store_conversation = AsyncMock(return_value=True)
    client.get_conversation = AsyncMock(return_value=None)
    client.add_message_to_conversation = AsyncMock(return_value=True)
    client.get_recent_messages = AsyncMock(return_value=[])
    client.store_active_session = AsyncMock(return_value=True)
    client.get_active_session = AsyncMock(return_value=None)
    client.is_conversation_active = AsyncMock(return_value=False)
    client.store_feature_history = AsyncMock(return_value=True)
    client.get_feature_history = AsyncMock(return_value=None)
    client.can_execute_feature = AsyncMock(return_value=True)
    client.set_cache = AsyncMock(return_value=True)
    client.get_cache = AsyncMock(return_value=None)
    client.delete_cache = AsyncMock(return_value=True)
    client.close = AsyncMock()

    return client


# ---------------------------------------------------------------------------
# SQLite client mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_client():
    """Mock SQLiteClient."""
    client = MagicMock()

    client.initialize = AsyncMock()
    client.create_guild = AsyncMock(return_value=True)
    client.get_guild = AsyncMock(return_value=None)
    client.create_channel = AsyncMock(return_value=True)
    client.get_channel = AsyncMock(return_value=None)
    client.create_character = AsyncMock(return_value=True)
    client.get_character = AsyncMock(return_value=None)
    client.create_schedule = AsyncMock(return_value=True)
    client.get_schedules = AsyncMock(return_value=[])
    client.update_schedule_execution = AsyncMock(return_value=True)
    client.close = AsyncMock()

    # Agent memory repo sub-mock (mirrors AgentMemoryRepo interface)
    memory = MagicMock()
    memory.upsert = AsyncMock(return_value=True)
    memory.get_memories = AsyncMock(return_value=[])
    memory.delete = AsyncMock(return_value=True)
    client.memory = memory

    # Persona repo sub-mock (mirrors PersonaRepo interface)
    persona = MagicMock()
    persona.seed_preset_personas = AsyncMock()
    persona.create_persona = AsyncMock(return_value=True)
    persona.get_persona = AsyncMock(return_value=None)
    persona.get_guild_personas = AsyncMock(return_value=[])
    persona.update_persona = AsyncMock(return_value=True)
    persona.delete_persona = AsyncMock(return_value=True)
    persona.count_guild_personas = AsyncMock(return_value=0)
    persona.set_guild_active_persona = AsyncMock(return_value=True)
    client.persona = persona

    return client


# ---------------------------------------------------------------------------
# Character manager mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_character_manager(mock_db_client, mock_openai_client):
    """Mock CharacterManager with dependencies injected."""
    manager = MagicMock()

    default_character = Character(
        guild_id="123456789012345678",
        name="らじたん",
        system_prompt="テスト用システムプロンプト。テスト環境で使用するプロンプトです。",
        personality_traits={"type": "default", "traits": {"friendliness": 0.8, "humor": 0.7, "energy": 0.6, "formality": 0.3, "helpfulness": 0.9}},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    manager.create_character = AsyncMock(return_value=True)
    manager.get_character = AsyncMock(return_value=default_character)
    manager.update_character = AsyncMock(return_value=True)
    manager.generate_response = AsyncMock(return_value="テスト応答です！")
    manager.should_use_feature = AsyncMock(return_value=True)
    manager.get_feature_timing = AsyncMock(return_value=30)
    manager.get_character_info = AsyncMock(
        return_value={
            "name": "らじたん",
            "personality_type": "default",
            "personality_traits": default_character.personality_traits["traits"],
            "created_at": default_character.created_at,
            "updated_at": default_character.updated_at,
        }
    )
    manager.clear_cache = MagicMock()
    manager.delete_character = AsyncMock(return_value=True)

    return manager


# ---------------------------------------------------------------------------
# Persona manager mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_persona_manager():
    """Mock PersonaManager."""
    manager = MagicMock()

    manager.resolve_persona = AsyncMock(return_value=None)
    manager.get_available_personas = AsyncMock(return_value=[])
    manager.set_guild_persona = AsyncMock(return_value=True)
    manager.create_custom_persona = AsyncMock(return_value=None)
    manager.update_custom_persona = AsyncMock(return_value=True)
    manager.delete_custom_persona = AsyncMock(return_value=True)
    manager._persona_cache = {}

    return manager


# ---------------------------------------------------------------------------
# Conversation tracker mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conversation_tracker(mock_redis_client):
    """Mock ConversationTracker."""
    tracker = MagicMock()

    tracker.track_message = AsyncMock(return_value=True)
    tracker.get_recent_conversation = AsyncMock(return_value=[])
    tracker.get_full_conversation = AsyncMock(return_value=None)
    tracker.is_conversation_active = AsyncMock(return_value=False)
    tracker.get_conversation_state = AsyncMock(return_value=ConversationState.INACTIVE)
    tracker.mark_conversation_end = AsyncMock(return_value=True)
    tracker.get_conversation_summary_data = AsyncMock(return_value=None)
    tracker.should_execute_feature = AsyncMock(return_value=False)
    tracker.get_conversation_stats = AsyncMock(
        return_value={
            "is_active": False,
            "message_count": 0,
            "participant_count": 0,
            "duration_minutes": 0,
        }
    )
    tracker.cleanup_old_conversations = AsyncMock(return_value=True)

    # Expose an analyzer mock for code paths that access tracker.conversation_analyzer
    tracker.conversation_analyzer = MagicMock()
    tracker.conversation_analyzer.analyze_conversation_activity = AsyncMock(
        return_value={"is_active": False, "message_count": 0, "participant_count": 0, "activity_level": "inactive"}
    )

    return tracker


# ---------------------------------------------------------------------------
# Bot mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bot(
    mock_db_client,
    mock_redis_client,
    mock_character_manager,
    mock_conversation_tracker,
    mock_openai_client,
):
    """Mock RajitanBot with all dependencies injected."""
    bot = MagicMock()

    bot.db_client = mock_db_client
    bot.redis_client = mock_redis_client
    bot.character_manager = mock_character_manager
    bot.conversation_tracker = mock_conversation_tracker
    bot.openai_client = mock_openai_client

    bot.conversation_summarizer = None
    bot.quiz_generator = None
    bot.quiz_runner = None
    bot.enhanced_schedule_manager = None
    bot.trigger_manager = None
    bot.music_recommender = None

    bot.start_time = datetime.now()
    bot.ready = True
    bot.user = MagicMock()
    bot.user.id = 999888777666555444
    bot.user.name = "Rajitan"
    bot.user.display_name = "らじたん"
    bot.guilds = []
    bot.latency = 0.05

    bot.send_message = AsyncMock(return_value=True)
    bot.inject_dependencies = MagicMock()
    bot.shutdown = AsyncMock()

    return bot


# ---------------------------------------------------------------------------
# Helper: sample messages
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_messages():
    """Create a list of sample Message objects for testing."""
    return [
        Message(user_id="111222333444555666", username="Alice", content="今日はいい天気だね", timestamp=datetime(2026, 2, 8, 10, 0)),
        Message(user_id="222333444555666777", username="Bob", content="本当に！散歩日和だよ", timestamp=datetime(2026, 2, 8, 10, 5)),
        Message(user_id="111222333444555666", username="Alice", content="音楽でも聴きながら歩こうかな", timestamp=datetime(2026, 2, 8, 10, 10)),
    ]
