"""Tests for rajitan.character.personality module."""

import pytest
from rajitan.character.personality import PersonalityManager, PersonalityType
from rajitan.character.prompts import PERSONALITY_TRAITS


@pytest.fixture
def personality_manager():
    return PersonalityManager()


# ---------------------------------------------------------------------------
# get_personality_traits
# ---------------------------------------------------------------------------

class TestGetPersonalityTraits:
    def test_default_personality_returns_correct_traits(self, personality_manager):
        traits = personality_manager.get_personality_traits("default")
        assert traits == PERSONALITY_TRAITS["default"]
        assert traits["friendliness"] == 0.8
        assert traits["humor"] == 0.7

    def test_cheerful_personality_has_high_energy(self, personality_manager):
        traits = personality_manager.get_personality_traits("cheerful")
        assert traits["energy"] == 0.8
        assert traits["friendliness"] == 0.9

    def test_calm_personality_has_low_energy(self, personality_manager):
        traits = personality_manager.get_personality_traits("calm")
        assert traits["energy"] == 0.4
        assert traits["humor"] == 0.5

    def test_unknown_personality_falls_back_to_default(self, personality_manager):
        traits = personality_manager.get_personality_traits("nonexistent")
        assert traits == PERSONALITY_TRAITS["default"]

    def test_all_personality_types_return_required_keys(self, personality_manager):
        required_keys = {"friendliness", "humor", "energy", "formality", "helpfulness"}
        for personality_type in PERSONALITY_TRAITS:
            traits = personality_manager.get_personality_traits(personality_type)
            assert required_keys.issubset(traits.keys()), f"Missing keys for {personality_type}"


# ---------------------------------------------------------------------------
# calculate_response_style
# ---------------------------------------------------------------------------

class TestCalculateResponseStyle:
    def test_high_energy_increases_temperature(self, personality_manager):
        # cheerful has energy 0.8 (> 0.7)
        style = personality_manager.calculate_response_style("cheerful", {"mood": "neutral"})
        assert style["temperature"] >= 0.8

    def test_low_energy_decreases_temperature(self, personality_manager):
        # calm has energy 0.4 (< 0.4)
        style = personality_manager.calculate_response_style("calm", {"mood": "neutral"})
        assert style["temperature"] <= 0.7

    def test_high_energy_increases_max_tokens(self, personality_manager):
        style = personality_manager.calculate_response_style("cheerful", {"mood": "neutral"})
        assert style["max_tokens"] > 300

    def test_excited_mood_raises_temperature(self, personality_manager):
        style_neutral = personality_manager.calculate_response_style("default", {"mood": "neutral"})
        style_excited = personality_manager.calculate_response_style("default", {"mood": "excited"})
        assert style_excited["temperature"] >= style_neutral["temperature"]

    def test_serious_mood_lowers_temperature(self, personality_manager):
        style_neutral = personality_manager.calculate_response_style("default", {"mood": "neutral"})
        style_serious = personality_manager.calculate_response_style("default", {"mood": "serious"})
        assert style_serious["temperature"] <= style_neutral["temperature"]

    def test_professional_formality_adjusts_style(self, personality_manager):
        # professional has formality 0.9 (> 0.6)
        style = personality_manager.calculate_response_style("professional", {"mood": "neutral"})
        assert style["frequency_penalty"] >= 0.3


# ---------------------------------------------------------------------------
# should_use_feature
# ---------------------------------------------------------------------------

class TestShouldUseFeature:
    def test_summary_with_high_helpfulness_and_many_messages(self, personality_manager):
        # default has helpfulness 0.9 -> base_probability = 0.72
        # message_count > 20 adds 0.2 -> 0.92 > 0.6 -> True
        result = personality_manager.should_use_feature("default", "summary", {"message_count": 25})
        assert result is True

    def test_quiz_with_cheerful_personality_and_positive_mood(self, personality_manager):
        # cheerful: energy=0.8, humor=0.8 -> (0.8+0.8)/2*0.7 = 0.56
        # positive mood adds 0.2 -> 0.76 > 0.5
        result = personality_manager.should_use_feature("cheerful", "quiz", {"mood": "positive"})
        assert result is True

    def test_quiz_with_serious_mood_reduces_probability(self, personality_manager):
        # professional: energy=0.5, humor=0.3 -> (0.5+0.3)/2*0.7 = 0.28
        # serious mood subtracts 0.3 -> -0.02 < 0.5
        result = personality_manager.should_use_feature("professional", "quiz", {"mood": "serious"})
        assert result is False

    def test_music_with_non_neutral_mood(self, personality_manager):
        # music: base_probability = 0.6, non-neutral adds 0.2 -> 0.8 > 0.5
        result = personality_manager.should_use_feature("default", "music", {"mood": "excited"})
        assert result is True

    def test_unknown_feature_returns_false(self, personality_manager):
        result = personality_manager.should_use_feature("default", "unknown_feature", {})
        assert result is False


# ---------------------------------------------------------------------------
# get_feature_timing
# ---------------------------------------------------------------------------

class TestGetFeatureTiming:
    def test_high_energy_reduces_interval(self, personality_manager):
        # cheerful has energy 0.8 -> summary base 30 * 0.8 = 24
        timing = personality_manager.get_feature_timing("cheerful", "summary")
        assert timing < 30

    def test_low_energy_does_not_reduce_interval(self, personality_manager):
        # calm has energy exactly 0.4 (not < 0.4), so the high-energy reduction
        # does not apply. But helpfulness 0.9 > 0.8 applies the summary bonus
        # (0.9x) for summary feature. base=30, 30*0.9=27
        timing = personality_manager.get_feature_timing("calm", "summary")
        # For quiz feature with calm personality (energy=0.4, not <0.4 and not >0.7),
        # the base interval stays unchanged
        quiz_timing = personality_manager.get_feature_timing("calm", "quiz")
        assert quiz_timing == 60  # unchanged from default base of 60

    def test_minimum_timing_is_5(self, personality_manager):
        timing = personality_manager.get_feature_timing("default", "summary")
        assert timing >= 5

    def test_unknown_feature_uses_default_base(self, personality_manager):
        timing = personality_manager.get_feature_timing("default", "unknown_feature")
        assert timing >= 5


# ---------------------------------------------------------------------------
# customize_prompt_for_personality
# ---------------------------------------------------------------------------

class TestCustomizePromptForPersonality:
    def test_high_energy_adds_genki_instruction(self, personality_manager):
        prompt = personality_manager.customize_prompt_for_personality("ベースプロンプト", "cheerful")
        assert "元気で活発" in prompt

    def test_calm_personality_does_not_add_genki_instruction(self, personality_manager):
        # calm has energy 0.4 which is exactly at boundary (not > 0.7 and not < 0.4)
        # so neither high-energy nor low-energy additions are applied
        prompt = personality_manager.customize_prompt_for_personality("ベースプロンプト", "calm")
        assert "元気で活発" not in prompt

    def test_high_formality_adds_polite_instruction(self, personality_manager):
        prompt = personality_manager.customize_prompt_for_personality("ベースプロンプト", "professional")
        assert "丁寧" in prompt

    def test_low_formality_adds_casual_instruction(self, personality_manager):
        # friendly has formality 0.2 (< 0.3)
        prompt = personality_manager.customize_prompt_for_personality("ベースプロンプト", "friendly")
        assert "カジュアル" in prompt

    def test_default_personality_preserves_base_prompt(self, personality_manager):
        base = "ベースプロンプト"
        prompt = personality_manager.customize_prompt_for_personality(base, "default")
        assert prompt.startswith(base)
