"""
ModelManager — Multi-model management with per-guild model selection.

Manages available LLM models, caches providers, and persists
per-guild model selections in SQLite.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from openai import AsyncOpenAI

from rajitan.agent.llm.base import LLMProvider
from rajitan.agent.llm.openai_provider import OpenAIProvider
from rajitan.utils.logger import get_logger

logger = get_logger("agent.llm.model_manager")


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    model_id: str
    display_name: str
    base_url: str
    api_key_env: str
    supports_thinking: bool
    supports_tools: bool = True


class ModelManager:
    """Manages available LLM models and per-guild model selection."""

    def __init__(self, db_client, default_model_id: str = "deepseek-chat"):
        self._models: Dict[str, ModelConfig] = {}
        self._providers: Dict[str, LLMProvider] = {}
        self._guild_cache: Dict[str, str] = {}
        self._db = db_client
        self._default_model_id = default_model_id

    def register(self, config: ModelConfig) -> bool:
        """Register a model. Returns False if the API key is not set."""
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            logger.info(f"Skipping model {config.model_id}: {config.api_key_env} not set")
            return False

        client = AsyncOpenAI(api_key=api_key, base_url=config.base_url)
        self._models[config.model_id] = config
        self._providers[config.model_id] = OpenAIProvider(client, config.model_id)
        logger.info(f"Registered model: {config.display_name} ({config.model_id})")
        return True

    def get_default(self) -> LLMProvider:
        """Get the default provider (for ResponseGate etc.)."""
        return self._providers[self._default_model_id]

    def get_default_model_id(self) -> str:
        """Get the default model ID."""
        return self._default_model_id

    async def get_provider(self, guild_id: str) -> LLMProvider:
        """Get the LLM provider for a guild (cached → SQLite → default)."""
        model_id = await self.get_guild_model_id(guild_id)
        provider = self._providers.get(model_id)
        if provider:
            return provider
        return self._providers[self._default_model_id]

    async def get_guild_model_id(self, guild_id: str) -> str:
        """Get the model_id for a guild (memory cache → SQLite → default)."""
        if guild_id in self._guild_cache:
            return self._guild_cache[guild_id]

        model_id = await self._db.get_guild_model(guild_id)
        if model_id and model_id in self._models:
            self._guild_cache[guild_id] = model_id
            return model_id

        return self._default_model_id

    async def set_guild_model(self, guild_id: str, model_id: str) -> bool:
        """Set the model for a guild (SQLite + cache update)."""
        if model_id not in self._models:
            return False
        success = await self._db.set_guild_model(guild_id, model_id)
        if success:
            self._guild_cache[guild_id] = model_id
        return success

    def list_available(self) -> List[ModelConfig]:
        """List all models with valid API keys."""
        return list(self._models.values())

    def get_config(self, model_id: str) -> Optional[ModelConfig]:
        """Get a ModelConfig by model_id."""
        return self._models.get(model_id)
