"""Typed settings from environment variables / the project's ``.env`` file.

Secrets are only read from the environment. Every other value has a sensible default, so StoryWeaver runs with
nothing but ``GROQ_API_KEY`` — locally or as a serverless deployment.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _key(name: str) -> AliasChoices:
    """API keys are accepted with or without the STORYWEAVER_ prefix (e.g. GROQ_API_KEY)."""
    return AliasChoices(name, f"STORYWEAVER_{name}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STORYWEAVER_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- secrets -------------------------------------------------------------------------------------
    groq_api_key: str = Field(default="", validation_alias=_key("GROQ_API_KEY"))
    gemini_api_key: str = Field(default="", validation_alias=_key("GEMINI_API_KEY"))
    cloudflare_api_token: str = Field(default="", validation_alias=_key("CLOUDFLARE_API_TOKEN"))
    cloudflare_account_id: str = Field(default="", validation_alias=_key("CLOUDFLARE_ACCOUNT_ID"))
    hf_token: str = Field(default="", validation_alias=_key("HF_TOKEN"))
    pollinations_key: str = Field(default="", validation_alias=_key("POLLINATIONS_KEY"))  # optional

    # --- server --------------------------------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # --- language models: an ordered fallback chain per agent role ("provider:model") ----------------
    route_guardian: str = "groq:openai/gpt-oss-safeguard-20b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite"
    # The whole story in one call: the fastest model first (gpt-oss-20b answers at ~1,000 tokens/s on Groq), then
    # models with their own separate free-tier limits.
    route_storyteller: str = ("groq:openai/gpt-oss-20b,groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b,"
                              "gemini:gemini-3.5-flash")
    route_writer: str = ("groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b,groq:openai/gpt-oss-20b,"
                         "gemini:gemini-3.5-flash")
    route_editor: str = "groq:qwen/qwen3.8-27b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite"
    # The listener's ear must answer in about a second, and right after a story is written gpt-oss-20b's per-minute
    # budget is spent (Groq limits are per model): the 120b model, rarely used otherwise, answers first.
    route_interpreter: str = ("groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite,"
                              "groq:qwen/qwen3.8-27b")
    # the evaluation's single-prompt baseline uses the same models as the Storyteller (a like-for-like comparison)
    route_baseline: str = ("groq:openai/gpt-oss-20b,groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b,"
                           "gemini:gemini-3.5-flash")
    prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"
    llm_timeout_s: float = 45.0

    # --- voices --------------------------------------------------------------------------------------
    kokoro_model_file: str = "kokoro-v1.0.onnx"
    # Load Kokoro and measure its speed at start-up, so "Auto" can pick it on a fast machine. Off by default: on a
    # modest laptop the measurement occupies every core for up to a minute — just when the first story starts.
    studio_warmup: bool = False
    gemini_tts_models: str = "gemini-3.8-flash-tts,gemini-3.8-flash-lite-tts"
    stt_model: str = "whisper-large-v3-turbo"
    stt_language: str = "en"

    # --- pictures ------------------------------------------------------------------------------------
    image_models: str = "@cf/black-forest-labs/flux-2-klein-4b,@cf/black-forest-labs/flux-1-schnell"
    video_space: str = ""  # optional Hugging Face Space for short clips (image-to-video), e.g. "owner/space"

    # Identifies the app to public APIs (Wikipedia etiquette asks for a contact in the User-Agent).
    contact: str = "https://github.com/SaadH-077"

    # --- paths ---------------------------------------------------------------------------------------
    models_dir: Path = PROJECT_ROOT / "models"
    public_dir: Path = PROJECT_ROOT / "public"

    def route(self, role: str) -> list[tuple[str, str]]:
        """The ordered (provider, model) chain for an agent role, skipping providers without keys."""
        chain = []
        for item in getattr(self, f"route_{role}").split(","):
            provider, _, model = item.strip().partition(":")
            if (provider == "groq" and self.groq_api_key) or (provider == "gemini" and self.gemini_api_key):
                chain.append((provider, model))
        return chain

    @property
    def kokoro_model_path(self) -> Path:
        return self.models_dir / "kokoro" / self.kokoro_model_file

    @property
    def kokoro_voices_path(self) -> Path:
        return self.models_dir / "kokoro" / "voices-v1.0.bin"

    @property
    def cloudflare_enabled(self) -> bool:
        return bool(self.cloudflare_api_token and self.cloudflare_account_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
