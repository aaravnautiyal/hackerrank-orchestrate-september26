"""
Secure Credentials Manager for Groq API.
Centralizes environment variable loading and key retrieval.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file at repository root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class CredentialsManager:
    @staticmethod
    def get_groq_api_key() -> str:
        """Retrieves Groq API key from environment."""
        key = os.getenv("GROQ_API_KEY")
        if not key or key.startswith("gsk_your_actual"):
            raise ValueError(
                "GROQ_API_KEY is missing or unconfigured in the .env file."
            )
        return key

    @staticmethod
    def get_groq_base_url() -> str:
        """Retrieves Groq Base URL."""
        return os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    @staticmethod
    def get_groq_model() -> str:
        """Retrieves Groq primary text model name."""
        return os.getenv("GROQ_MODEL_NAME", "llama-3.3-70b-versatile")

    @staticmethod
    def get_groq_vision_model() -> str:
        """Retrieves Groq vision-compatible model name."""
        return os.getenv("GROQ_VISION_MODEL_NAME", "llama-3.2-11b-vision-instruct")

    @staticmethod
    def get_key(key_name: str, default: Optional[str] = None) -> Optional[str]:
        """Generic fetcher for any environment variable."""
        return os.getenv(key_name, default)