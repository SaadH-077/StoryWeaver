"""Speech-to-text for push-to-talk, using Whisper large-v3-turbo on Groq (free tier)."""

from __future__ import annotations

import httpx

from ..config import Settings


class TranscriptionError(RuntimeError):
    pass


async def transcribe(audio: bytes, filename: str, content_type: str, settings: Settings) -> str:
    if not settings.groq_api_key:
        raise TranscriptionError("Voice input needs GROQ_API_KEY.")
    if len(audio) < 1200:
        return ""
    data = {"model": settings.stt_model, "response_format": "json", "temperature": "0"}
    if settings.stt_language:
        data["language"] = settings.stt_language
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            data=data,
            files={"file": (filename or "speech.webm", audio, content_type or "audio/webm")},
        )
    if resp.status_code != 200:
        raise TranscriptionError(f"Transcription failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("text", "").strip()
