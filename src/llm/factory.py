"""LLM provider factory for creating provider instances."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings, get_settings
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """Factory for creating LLM provider instances.
    
    Supports dynamic provider registration and runtime switching.
    """

    _providers: dict[str, type] = {}

    @classmethod
    def _ensure_registered(cls) -> None:
        """Lazy registration of built-in providers."""
        if cls._providers:
            return
        
        from src.llm.providers.openai_provider import OpenAIProvider
        from src.llm.providers.anthropic_provider import AnthropicProvider
        from src.llm.providers.google_provider import GoogleProvider
        from src.llm.providers.ollama_provider import OllamaProvider
        
        cls._providers = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "google": GoogleProvider,
            "ollama": OllamaProvider,
        }

    @classmethod
    def register(cls, name: str, provider_class: type) -> None:
        """Register a custom provider class.
        
        Args:
            name: Provider name (e.g., 'custom')
            provider_class: Provider class implementing LLMProvider
        """
        cls._ensure_registered()
        cls._providers[name] = provider_class
        logger.info(f"Registered LLM provider: {name}")

    @classmethod
    def create(
        cls,
        provider_name: str | None = None,
        model: str | None = None,
        settings: Settings | None = None,
        **kwargs: Any,
    ) -> LLMProvider:
        """Create an LLM provider instance.
        
        Args:
            provider_name: Provider name (uses settings default if None)
            model: Model name (uses provider default if None)
            settings: Settings instance (uses cached if None)
            **kwargs: Additional provider-specific arguments
            
        Returns:
            Configured LLMProvider instance
            
        Raises:
            ValueError: If provider is unknown or misconfigured
        """
        cls._ensure_registered()
        
        settings = settings or get_settings()
        name = provider_name or settings.llm_provider
        
        if name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(f"Unknown provider: {name}. Available: {available}")
        
        provider_class = cls._providers[name]
        
        # Build provider-specific configuration
        default_model = model or settings.llm_model

        if name == "openai":
            config = {
                "api_key": settings.openai_api_key,
                "model": model or settings.openai_agent_model,
                "embedding_model": settings.openai_embedding_model,
            }
        elif name == "anthropic":
            config = {
                "api_key": settings.anthropic_api_key,
                "model": default_model if default_model else "claude-3-5-sonnet-20241022",
            }
        elif name == "google":
            config = {
                "api_key": settings.google_api_key,
                "model": default_model if default_model else "gemini-2.0-flash",
            }
        elif name == "ollama":
            config = {
                "base_url": settings.ollama_base_url,
                "model": model or "llama3.2",
            }
        else:
            config = {"model": model} if model else {}
        
        # Merge with any extra kwargs
        config.update(kwargs)
        
        logger.info(f"Creating LLM provider: {name} (model: {config.get('model', 'default')})")
        
        return provider_class(**config)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """List available provider names."""
        cls._ensure_registered()
        return list(cls._providers.keys())

    @classmethod
    def is_provider_configured(cls, provider_name: str, settings: Settings | None = None) -> bool:
        """Check if a provider has required configuration.
        
        Args:
            provider_name: Provider name to check
            settings: Settings instance
            
        Returns:
            True if provider is properly configured
        """
        settings = settings or get_settings()
        
        if provider_name == "openai":
            return bool(settings.openai_api_key)
        elif provider_name == "anthropic":
            return bool(settings.anthropic_api_key)
        elif provider_name == "google":
            return bool(settings.google_api_key)
        elif provider_name == "ollama":
            return True  # No API key needed
        
        return False
