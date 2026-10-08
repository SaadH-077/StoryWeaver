"""Server-side text-to-speech engines (the browser's own neural voices are the third engine, see public/js).

* ``neural`` — Microsoft's neural voices via edge-tts: ~1-2 s per sentence, free, no key, works when deployed.
  The browser fetches every sentence of the (already written) story in parallel, so narration never waits.
* ``studio`` — Kokoro-82M (Apache-2.0) on the server's CPU via ONNX Runtime: unlimited, private, offline.
  Optional (``uv sync --extra local``); its real-time factor is measured at start-up so the client can decide
  whether it is fast enough for continuous playback on this machine.
* ``cloud``  — Gemini Flash TTS (free tier): very expressive (per-line performance directions), rate-limited;
  rotates between two TTS models to spread the quota.

Results are cached in memory (no disk writes — works on serverless platforms).
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import importlib.util
import io
import logging
import threading
import time
import wave
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from .voices import DELIVERY_SPEED, DELIVERY_STYLE

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Speech:
    audio: bytes
    duration: float
    engine: str
    voice: str
    mime: str = "audio/wav"


class TTSError(RuntimeError):
    pass


def _wav_duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / float(w.getframerate())


def _pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buffer.getvalue()


class StudioEngine:
    """Kokoro-82M on CPU. One worker: ONNX Runtime already uses every core for one inference."""

    name = "studio"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Any = None
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kokoro")
        self.real_time_factor: float | None = None

    @property
    def available(self) -> bool:
        # find_spec, not import: answering "is it installed?" must not load ONNX Runtime into memory
        if not all(importlib.util.find_spec(m) for m in ("kokoro_onnx", "soundfile")):
            return False
        return self.settings.kokoro_model_path.exists() and self.settings.kokoro_voices_path.exists()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from kokoro_onnx import Kokoro

                log.info("Loading Kokoro voice model %s", self.settings.kokoro_model_path.name)
                self._model = Kokoro(str(self.settings.kokoro_model_path), str(self.settings.kokoro_voices_path))
                logging.getLogger("phonemizer").setLevel(logging.ERROR)  # harmless word-count notices
        return self._model

    def _synthesize(self, text: str, voice: str, speed: float) -> Speech:
        import numpy as np
        import soundfile as sf

        samples, rate = self._load().create(text, voice=voice, speed=speed, lang="en-us")
        samples = np.asarray(samples, dtype=np.float32)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak > 0:
            samples = samples * (0.89 / peak)
        buffer = io.BytesIO()
        sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
        return Speech(buffer.getvalue(), len(samples) / rate, self.name, voice)

    async def warmup(self) -> None:
        """Load the model and measure the real-time factor (compute time / audio time) on this machine."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._load)
        started = time.perf_counter()
        speech = await loop.run_in_executor(self._executor, self._synthesize,
                                            "Once upon a time, in a quiet little town, there lived a curious fox.",
                                            "bf_emma", 1.0)
        self.real_time_factor = round((time.perf_counter() - started) / max(speech.duration, 0.1), 2)
        log.info("Studio voices ready — real-time factor %.2f", self.real_time_factor)

    async def synthesize(self, text: str, voice: dict[str, Any], delivery: str) -> Speech:
        speed = round(float(voice.get("speed", 1.0)) * DELIVERY_SPEED.get(delivery, 1.0), 3)
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, self._synthesize, text, str(voice.get("kokoro", "bf_emma")), speed)


# delivery -> (speaking rate, pitch) for the neural voices
NEURAL_PROSODY = {"neutral": ("+0%", "+0Hz"), "warm": ("-3%", "+0Hz"), "calm": ("-6%", "-2Hz"),
                  "excited": ("+8%", "+4Hz"), "playful": ("+5%", "+3Hz"), "whisper": ("-10%", "-3Hz"),
                  "tense": ("+4%", "+1Hz"), "scared": ("+6%", "+4Hz"), "sad": ("-10%", "-4Hz"), "awe": ("-7%", "+2Hz")}


class NeuralEngine:
    """Microsoft neural voices through edge-tts (no key). Each sentence takes ~1-2 s; the browser asks for all of a
    story's sentences ahead of time, so they are ready long before they are spoken."""

    name = "neural"
    TIMEOUT_S = 8.0

    def __init__(self, settings: Settings):
        self.settings = settings
        self._sem = asyncio.Semaphore(6)

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("edge_tts") is not None

    async def synthesize(self, text: str, voice: dict[str, Any], delivery: str) -> Speech:
        import edge_tts

        voice_name = str(voice.get("edge") or "en-US-AvaNeural")
        rate, pitch = NEURAL_PROSODY.get(delivery, ("+0%", "+0Hz"))
        speed = float(voice.get("speed") or 1.0)
        if speed != 1.0:  # children speak a little faster, elders slower
            rate = f"{int(rate.strip('%')) + round((speed - 1) * 100):+d}%"
        if float(voice.get("pitch") or 1.0) > 1.05:
            pitch = f"{int(pitch.rstrip('Hz')) + 8:+d}Hz"

        async def run() -> bytes:
            data = bytearray()
            async for chunk in edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch).stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return bytes(data)

        async with self._sem:
            audio = await asyncio.wait_for(run(), self.TIMEOUT_S)
        if not audio:
            raise TTSError("empty audio")
        return Speech(audio, len(text.split()) / 2.6, self.name, voice_name, "audio/mpeg")


class CloudEngine:
    """Gemini Flash TTS with per-line style directions; rotates models to spread the free quota."""

    name = "cloud"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.models = [m.strip() for m in settings.gemini_tts_models.split(",") if m.strip()]
        self._client: Any = None
        self._sem = asyncio.Semaphore(3)
        self._turn = 0
        # its own threads: a hung SDK call must never occupy the event loop's default pool (which also resolves DNS
        # for every other request)
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="gemini-tts")

    @property
    def available(self) -> bool:
        return bool(self.settings.gemini_api_key and self.models)

    def _client_obj(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    async def synthesize(self, text: str, voice: dict[str, Any], delivery: str) -> Speech:
        style = DELIVERY_STYLE.get(delivery, "natural storytelling")
        if voice.get("persona"):
            style = f"{style}; voice of {voice['persona']}"[:200]
        voice_name = str(voice.get("gemini", "Sulafat"))
        errors = []
        loop = asyncio.get_running_loop()
        for attempt in range(min(2, len(self.models))):
            model = self.models[(self._turn + attempt) % len(self.models)]
            try:
                async with self._sem:
                    call = functools.partial(
                        self._client_obj().interactions.create, model=model,
                        input=[{"type": "user_input", "content": [{"type": "text", "text": text, "annotations": [
                            {"type": "speech_metadata", "style": style}]}]}],
                        response_format={"type": "audio"},
                        generation_config={"speech_config": [{"voice": voice_name}]})
                    interaction = await asyncio.wait_for(loop.run_in_executor(self._executor, call), timeout=8)
                data = base64.b64decode(interaction.output_audio.data)
                if not data.startswith(b"RIFF"):
                    data = _pcm_to_wav(data)
                self._turn += 1
                return Speech(data, _wav_duration(data), self.name, voice_name)
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}")
        raise TTSError("; ".join(errors))


class TTSService:
    """Front door for server-side speech with an in-memory LRU cache and engine fallback."""

    def __init__(self, settings: Settings, cache_size: int = 400):
        self.neural = NeuralEngine(settings)
        self.studio = StudioEngine(settings)
        self.cloud = CloudEngine(settings)
        self._cache: OrderedDict[str, Speech] = OrderedDict()
        self._cache_size = cache_size

    def engines(self) -> dict[str, dict[str, Any]]:
        return {"neural": {"available": self.neural.available},
                "studio": {"available": self.studio.available, "real_time_factor": self.studio.real_time_factor},
                "cloud": {"available": self.cloud.available}}

    async def speak(self, text: str, voice: dict[str, Any], delivery: str = "neutral",
                    engine: str = "studio") -> Speech:
        key = hashlib.sha1(f"{engine}|{sorted(voice.items())}|{delivery}|{text}".encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        order = {"neural": [self.neural, self.cloud], "cloud": [self.cloud, self.neural],
                 "studio": [self.studio, self.neural]}.get(engine, [self.neural])
        errors = []
        for candidate in order:
            if not candidate.available:
                continue
            try:
                speech = await candidate.synthesize(text, voice, delivery)
            except Exception as exc:
                errors.append(f"{candidate.name}: {exc}")
                continue
            self._cache[key] = speech
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return speech
        raise TTSError("no server voice engine available" + (f" ({'; '.join(errors)})" if errors else ""))
