"""Configuration management for the Ruby agent."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Provider Configuration
    llm_provider: Literal["openai", "anthropic", "google", "ollama"] = "openai"
    llm_model: str = "gpt-4o"
    hybrid_routing: bool = True
    hybrid_routing_model: str = "function-gemma"

    # OpenAI Configuration
    openai_api_key: str = ""
    openai_agent_model: str = "gpt-4o"
    openai_memory_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic Configuration (Optional)
    anthropic_api_key: str = ""

    # Google Configuration (Optional)
    google_api_key: str = ""

    # Ollama Configuration (Optional)
    ollama_base_url: str = "http://localhost:11434"

    # Database Configuration
    database_provider: Literal["inmemory", "sqlite", "postgres"] = "inmemory"
    database_path: str = "./data/memu.db"
    database_url: str = ""  # For postgres

    # Logging Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "text"

    # Agent Configuration
    agent_name: str = "Ruby Assistant"
    agent_max_history: int = 20
    agent_max_memory_items: int = 10

    # Email Configuration (Gmail/Default)
    email_host: str = "smtp.gmail.com"
    email_port: int = 587
    email_user: str = ""
    email_password: str = ""

    # Outlook Configuration
    outlook_host: str = "smtp.office365.com"
    outlook_port: int = 587
    outlook_user: str = ""
    outlook_password: str = ""
    
    # Browser Configuration
    browser_user_data_dir: str = "./data/browser_profile"

    # Automation Configuration
    email_cleanup_interval: int = 3600  # Default 1 hour
    discovery_interval: int = 14400     # Default 4 hours
    reflection_interval: int = 7200     # Default 2 hours

    def get_email_credentials(self, account: str = "gmail") -> dict[str, Any]:
        """Get credentials for a specific email account."""
        if account.lower() == "outlook":
            return {
                "host": self.outlook_host,
                "port": self.outlook_port,
                "user": self.outlook_user,
                "password": self.outlook_password
            }
        # Default to primary (gmail)
        return {
            "host": self.email_host,
            "port": self.email_port,
            "user": self.email_user,
            "password": self.email_password
        }

    @property
    def data_dir(self) -> Path:
        """Get the data directory path."""
        path = Path(self.database_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_ruby_llm_profiles(self) -> dict:
        """Build Ruby-compatible LLM profiles configuration."""
        profiles = {
            # Default profile for Ruby's internal operations
            "default": {
                "backend": "openai",
                "api_key": self.openai_api_key,
                "chat_model": self.openai_memory_model,
            },
            # Embedding profile
            "embedding": {
                "backend": "openai",
                "api_key": self.openai_api_key,
                "embed_model": self.openai_embedding_model,
            },
        }
        return profiles

    def get_ruby_database_config(self) -> dict:
        """Build Ruby-compatible database configuration."""
        if self.database_provider == "inmemory":
            return {"metadata_store": {"provider": "inmemory"}}
        elif self.database_provider == "sqlite":
            return {
                "metadata_store": {
                    "provider": "sqlite",
                    "database_path": self.database_path,
                }
            }
        elif self.database_provider == "postgres":
            return {
                "metadata_store": {
                    "provider": "postgres",
                    "database_url": self.database_url,
                }
            }
        return {"metadata_store": {"provider": "inmemory"}}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
