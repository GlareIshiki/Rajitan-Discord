"""Tests for rajitan.utils.validators module."""

import pytest
from rajitan.utils.validators import (
    validate_discord_id,
    validate_character_name,
    validate_system_prompt,
    validate_interval,
    validate_message_content,
    sanitize_input,
)


# ---------------------------------------------------------------------------
# validate_discord_id
# ---------------------------------------------------------------------------

class TestValidateDiscordId:
    def test_valid_17_digit_id(self):
        assert validate_discord_id("12345678901234567") is True

    def test_valid_18_digit_id(self):
        assert validate_discord_id("123456789012345678") is True

    def test_valid_19_digit_id(self):
        assert validate_discord_id("1234567890123456789") is True

    def test_valid_integer_id(self):
        assert validate_discord_id(123456789012345678) is True

    def test_invalid_too_short(self):
        assert validate_discord_id("1234567890123456") is False

    def test_invalid_too_long(self):
        assert validate_discord_id("12345678901234567890") is False

    def test_invalid_non_numeric(self):
        assert validate_discord_id("abcdefghijklmnopq") is False

    def test_invalid_empty_string(self):
        assert validate_discord_id("") is False

    def test_invalid_none(self):
        assert validate_discord_id(None) is False


# ---------------------------------------------------------------------------
# validate_character_name
# ---------------------------------------------------------------------------

class TestValidateCharacterName:
    def test_accepts_ascii_name(self):
        assert validate_character_name("Rajitan") is True

    def test_accepts_japanese_name(self):
        assert validate_character_name("らじたん") is True

    def test_accepts_mixed_name(self):
        assert validate_character_name("Bot-らじたん") is True

    def test_rejects_empty_string(self):
        assert validate_character_name("") is False

    def test_rejects_none(self):
        assert validate_character_name(None) is False

    def test_rejects_too_long_name(self):
        long_name = "a" * 33
        assert validate_character_name(long_name) is False

    def test_accepts_max_length_name(self):
        name_32 = "a" * 32
        assert validate_character_name(name_32) is True

    def test_rejects_control_characters(self):
        assert validate_character_name("test\x00name") is False

    def test_rejects_control_character_tab(self):
        assert validate_character_name("test\tname") is False

    def test_accepts_single_character(self):
        assert validate_character_name("A") is True


# ---------------------------------------------------------------------------
# validate_system_prompt
# ---------------------------------------------------------------------------

class TestValidateSystemPrompt:
    def test_valid_prompt(self):
        prompt = "あなたはDiscordサーバーのラジオDJキャラクターです。"
        assert validate_system_prompt(prompt) is True

    def test_rejects_empty_string(self):
        assert validate_system_prompt("") is False

    def test_rejects_none(self):
        assert validate_system_prompt(None) is False

    def test_rejects_too_short_prompt(self):
        assert validate_system_prompt("短い") is False

    def test_rejects_whitespace_only_short_prompt(self):
        assert validate_system_prompt("         ") is False

    def test_rejects_too_long_prompt(self):
        long_prompt = "x" * 2001
        assert validate_system_prompt(long_prompt) is False

    def test_accepts_exactly_2000_characters(self):
        prompt = "x" * 2000
        assert validate_system_prompt(prompt) is True

    def test_accepts_prompt_with_10_stripped_chars(self):
        prompt = "1234567890"
        assert validate_system_prompt(prompt) is True

    def test_rejects_prompt_with_9_stripped_chars(self):
        prompt = "123456789"
        assert validate_system_prompt(prompt) is False


# ---------------------------------------------------------------------------
# validate_interval
# ---------------------------------------------------------------------------

class TestValidateInterval:
    def test_valid_minimum(self):
        assert validate_interval(5) is True

    def test_valid_maximum(self):
        assert validate_interval(1440) is True

    def test_valid_middle(self):
        assert validate_interval(60) is True

    def test_invalid_below_minimum(self):
        assert validate_interval(4) is False

    def test_invalid_above_maximum(self):
        assert validate_interval(1441) is False

    def test_invalid_zero(self):
        assert validate_interval(0) is False

    def test_invalid_negative(self):
        assert validate_interval(-1) is False

    def test_invalid_float(self):
        assert validate_interval(5.5) is False

    def test_invalid_string(self):
        assert validate_interval("60") is False


# ---------------------------------------------------------------------------
# validate_message_content
# ---------------------------------------------------------------------------

class TestValidateMessageContent:
    def test_valid_message(self):
        assert validate_message_content("こんにちは！") is True

    def test_rejects_empty_string(self):
        assert validate_message_content("") is False

    def test_rejects_none(self):
        assert validate_message_content(None) is False

    def test_rejects_too_long_message(self):
        long_message = "a" * 2001
        assert validate_message_content(long_message) is False

    def test_accepts_exactly_2000_characters(self):
        message = "a" * 2000
        assert validate_message_content(message) is True


# ---------------------------------------------------------------------------
# sanitize_input
# ---------------------------------------------------------------------------

class TestSanitizeInput:
    def test_removes_control_characters(self):
        result = sanitize_input("hello\x00world")
        assert result == "helloworld"

    def test_removes_null_bytes(self):
        result = sanitize_input("test\x00\x01\x02")
        assert result == "test"

    def test_trims_whitespace(self):
        result = sanitize_input("  hello world  ")
        assert result == "hello world"

    def test_empty_input(self):
        result = sanitize_input("")
        assert result == ""

    def test_none_input(self):
        result = sanitize_input(None)
        assert result == ""

    def test_preserves_japanese_characters(self):
        result = sanitize_input("  こんにちは世界  ")
        assert result == "こんにちは世界"

    def test_removes_escape_sequences(self):
        result = sanitize_input("line1\x1bline2")
        assert result == "line1line2"
