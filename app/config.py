"""
Application configuration loaded from environment variables.
Supports DeepSeek API and Ollama (Vast.ai) as LLM backends.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # --- LLM Provider ---
    llm_provider: Literal["deepseek", "ollama"] = Field(
        default="deepseek",
        description="Which LLM provider to use"
    )

    # --- DeepSeek API ---
    deepseek_api_key: str = Field(
        default="",
        description="DeepSeek API key"
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        description="DeepSeek API base URL"
    )
    deepseek_model: str = Field(
        default="deepseek-chat",
        description="DeepSeek model name (deepseek-chat or deepseek-reasoner)"
    )

    # --- Ollama (Vast.ai) ---
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="Ollama API base URL (OpenAI-compatible endpoint)"
    )
    ollama_model: str = Field(
        default="gemma3:27b",
        description="Ollama model name"
    )

    # --- API Server ---
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # --- Generation Settings ---
    max_scenes: int = Field(
        default=10,
        description="Maximum number of scenes to generate"
    )
    default_duration: int = Field(
        default=120,
        description="Default video duration in seconds"
    )
    creative_temperature: float = Field(
        default=0.8,
        description="Temperature for creative agents (story, script)"
    )
    structured_temperature: float = Field(
        default=0.4,
        description="Temperature for structured output agents (prompts)"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @property
    def llm_api_key(self) -> str:
        """Get the API key for the active LLM provider."""
        if self.llm_provider == "deepseek":
            return self.deepseek_api_key
        # Ollama typically doesn't need an API key
        return "ollama"

    @property
    def llm_base_url(self) -> str:
        """Get the base URL for the active LLM provider."""
        if self.llm_provider == "deepseek":
            return self.deepseek_base_url
        return self.ollama_base_url

    @property
    def llm_model(self) -> str:
        """Get the model name for the active LLM provider."""
        if self.llm_provider == "deepseek":
            return self.deepseek_model
        return self.ollama_model


# Singleton settings instance
settings = Settings()
