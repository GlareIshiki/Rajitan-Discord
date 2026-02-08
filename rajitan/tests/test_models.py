"""Tests for rajitan.storage.models module."""

import pytest
from datetime import datetime
from rajitan.storage.models import (
    Message,
    Conversation,
    Character,
    MusicRecommendation,
    Schedule,
    ConversationState,
)


class TestMessage:
    def test_creation_with_defaults(self):
        msg = Message(user_id="123", username="TestUser", content="Hello")
        assert msg.user_id == "123"
        assert msg.username == "TestUser"
        assert msg.content == "Hello"
        assert isinstance(msg.timestamp, datetime)

    def test_creation_with_explicit_timestamp(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        msg = Message(user_id="123", username="User", content="Test", timestamp=ts)
        assert msg.timestamp == ts


class TestConversation:
    def test_creation_with_defaults(self):
        conv = Conversation(channel_id="chan_001")
        assert conv.channel_id == "chan_001"
        assert conv.messages == []
        assert conv.message_count == 0
        assert conv.participants == []
        assert conv.state == ConversationState.INACTIVE
        assert isinstance(conv.last_activity, datetime)

    def test_creation_with_message_list(self):
        messages = [
            Message(user_id="u1", username="Alice", content="Hi"),
            Message(user_id="u2", username="Bob", content="Hello"),
        ]
        conv = Conversation(
            channel_id="chan_002",
            messages=messages,
            message_count=2,
            participants=["u1", "u2"],
        )
        assert len(conv.messages) == 2
        assert conv.message_count == 2
        assert "u1" in conv.participants


class TestCharacter:
    def test_creation_with_personality_traits(self):
        traits = {"type": "cheerful", "traits": {"energy": 0.8, "humor": 0.8}}
        char = Character(
            guild_id="guild_001",
            name="らじたん",
            system_prompt="テスト用システムプロンプト。テスト環境で使用する長めのプロンプト。",
            personality_traits=traits,
        )
        assert char.guild_id == "guild_001"
        assert char.name == "らじたん"
        assert char.personality_traits["type"] == "cheerful"
        assert isinstance(char.created_at, datetime)
        assert isinstance(char.updated_at, datetime)

    def test_creation_without_personality_traits(self):
        char = Character(
            guild_id="guild_002",
            name="TestBot",
            system_prompt="テスト用のシステムプロンプトです。テスト環境で使用します。",
        )
        assert char.personality_traits is None


class TestMusicRecommendation:
    def test_creation(self):
        rec = MusicRecommendation(
            title="Lemon",
            artist="米津玄師",
            url="https://www.youtube.com/watch?v=test",
            reason="穏やかな雰囲気に合う曲です。",
            channel_id="chan_003",
        )
        assert rec.title == "Lemon"
        assert rec.artist == "米津玄師"
        assert rec.url.startswith("https://")
        assert rec.reason != ""
        assert rec.channel_id == "chan_003"
        assert isinstance(rec.created_at, datetime)


class TestSchedule:
    def test_creation_with_all_fields(self):
        now = datetime.now()
        sched = Schedule(
            id=1,
            channel_id="chan_004",
            guild_id="guild_004",
            schedule_type="PERIODIC",
            function_type="summary",
            custom_message=None,
            pattern_type="daily",
            hour=19,
            minute=0,
            day_of_week=None,
            day_of_month=None,
            specific_datetime=None,
            is_active=True,
            created_by="user_001",
            created_at=now,
            last_executed=None,
            next_execution=None,
        )
        assert sched.id == 1
        assert sched.schedule_type == "PERIODIC"
        assert sched.function_type == "summary"
        assert sched.pattern_type == "daily"
        assert sched.hour == 19
        assert sched.is_active is True
        assert sched.created_by == "user_001"

    def test_creation_one_time(self):
        target = datetime(2026, 3, 1, 18, 0, 0)
        sched = Schedule(
            channel_id="chan_005",
            guild_id="guild_005",
            schedule_type="ONE_TIME",
            function_type="music",
            pattern_type="once",
            specific_datetime=target,
            created_by="user_002",
        )
        assert sched.schedule_type == "ONE_TIME"
        assert sched.specific_datetime == target


class TestConversationState:
    def test_enum_values(self):
        assert ConversationState.INACTIVE == "inactive"
        assert ConversationState.ACTIVE == "active"
        assert ConversationState.COOLING_DOWN == "cooling"
        assert ConversationState.FEATURE_EXECUTING == "executing"

    def test_enum_membership(self):
        assert "inactive" in [e.value for e in ConversationState]
        assert "active" in [e.value for e in ConversationState]
