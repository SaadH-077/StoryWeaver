"""Illustrations: a picture-book scene for every story moment, with characters that stay recognisable.

Providers (each one a fallback for the others):
1. FLUX.2 [klein] 4B on Cloudflare Workers AI — accepts *reference images*: we pass the cast's portraits so a
   character looks the same in every scene. Its latency on the free tier varies from ~4 s to a minute;
2. FLUX.1 [schnell] on Cloudflare Workers AI — fast (~2 s), no references;
3. Pollinations.ai — with a key if one is configured, otherwise its legacy anonymous endpoint (best effort:
   spaced ~16 s apart without a key, and paused briefly once it answers "402 / 429");
4. the picture shelf — ready-made storybook backdrops shipped with the app, matched to the scene by keywords
   (instant, no quota: what the listener sees when every free allowance is spent);
5. (in the browser) an animated paper-cut backdrop, if even the shelf is empty.

Every request says how long until the picture is on screen (``deadline``). The service keeps a moving average of
each provider's real latency and uses the reference-consistent model only when it can deliver in time — so the
opening picture and the portraits come from the fast model, and scenes prepared a chapter ahead get FLUX.2.

When Cloudflare's free daily allowance runs out (error 4006) it is skipped until it resets at 00:00 UTC, so no
picture waits on a request that can only fail.

Prompts are composed here from the scene, the story's art style and the characters' fixed looks, and always carry
a child-safe, no-text suffix. Results are cached in memory (no disk writes).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from ..config import Settings
from ..safety import lexicon
from . import picture_shelf

log = logging.getLogger(__name__)

SAFE_SUFFIX = ("gentle and wholesome, suitable for all ages, wordless scene with no text, letters, signs, captions or "
               "watermarks")


@dataclass(frozen=True)
class Picture:
    data: bytes
    provider: str
    mime: str = "image/jpeg"


class ImageError(RuntimeError):
    pass


def compose_prompt(description: str, style: str, looks: list[str], kind: str = "scene") -> str:
    cast = f" Characters: {'; '.join(looks)}." if looks else ""
    framing = ("Character portrait, centred, head and shoulders, plain soft background." if kind == "portrait"
               else "Wide cinematic storybook illustration.")
    return f"{framing} {description}.{cast} Style: {style}. {SAFE_SUFFIX}."[:1900]


class ImageService:
    def __init__(self, settings: Settings, cache_size: int = 120):
        self.settings = settings
        self.models = [m.strip() for m in settings.image_models.split(",") if m.strip()]
        self._cache: OrderedDict[str, Picture] = OrderedDict()
        self._cache_size = cache_size
        self._sem = asyncio.Semaphore(3)
        # expected seconds per picture, updated from every call (exponential moving average)
        self.expected = {"klein": 8.0, "schnell": 3.0, "pollinations": 5.0}
        self._paced = asyncio.Lock()  # Pollinations: one request at a time
        self._last_pollinations = 0.0
        self._pollinations_queue = 0
        self._paused_until = 0.0  # Pollinations said "no budget" / "too many": leave it alone until then
        self._cloud_out_until = 0.0  # Cloudflare's daily allowance is used up (or it is rate limiting) until then

    @property
    def cloud_ready(self) -> bool:
        return self.settings.cloudflare_enabled and time.monotonic() >= self._cloud_out_until

    @property
    def providers(self) -> list[str]:
        cloud = [m.rsplit("/", 1)[-1] for m in self.models] if self.cloud_ready else []
        return [*cloud, "pollinations", *(["shelf"] if picture_shelf.ready() else [])]

    async def generate(self, prompt: str, width: int, height: int, references: list[bytes] | None = None,
                       deadline: float | None = None, shelf: str | None = None) -> Picture:
        """Paint a picture; ``deadline`` = seconds until it is shown (None: no hurry, 0: as soon as possible).

        ``shelf``: the scene's description — if no live painter can deliver, the best-matching ready-made backdrop
        is returned instead (scenes only; a portrait has no stand-in)."""
        if lexicon.worst(lexicon.scan(prompt)) == "block":
            raise ImageError("unsafe picture description")
        key = hashlib.sha1(f"{width}x{height}|{prompt}|{len(references or [])}".encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        errors = []
        async with self._sem:
            for name in self.plan(deadline):
                attempt = {"klein": self._klein, "schnell": self._schnell, "pollinations": self._pollinations}[name]
                # a slow provider may not hold the story up for long: past its budget, the next one paints instead
                budget = 75.0 if deadline is None else max(deadline, 10.0) + 5.0
                started = time.perf_counter()
                try:
                    picture = await asyncio.wait_for(attempt(prompt, width, height, references or []), budget)
                except Exception as exc:
                    self._observe(name, time.perf_counter() - started)
                    errors.append(f"{name}: {type(exc).__name__} {str(exc)[:120]}")
                    log.warning("Image provider failed: %s", errors[-1])
                    continue
                seconds = time.perf_counter() - started
                self._observe(name, seconds)
                log.info("Picture %dx%d by %s in %.1f s", width, height, picture.provider, seconds)
                self._cache[key] = picture
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
                return picture
        backdrop = picture_shelf.pick(shelf) if shelf else None
        if backdrop:  # not cached: once a painter is back, this scene gets its own picture
            log.info("Picture from the shelf: %s (%s)", backdrop.id, "; ".join(errors) or "no painter free in time")
            return Picture(backdrop.path.read_bytes(), f"shelf:{backdrop.id}")
        raise ImageError("; ".join(errors) or "no image provider")

    def plan(self, deadline: float | None) -> list[str]:
        """Provider order for one picture: FLUX.2 (with character references) first when it can deliver in time."""
        cloud = self.cloud_ready
        # anonymous Pollinations answers about once every 15 s: if the queue is longer than the picture can wait,
        # the shelf answers at once instead
        pollinations = (time.monotonic() >= self._paused_until
                        and (deadline is None or self._pollinations_wait() <= max(deadline, 4.0)))
        available = {"klein": cloud and any("flux-2" in m for m in self.models),
                     "schnell": cloud and any("flux-1" in m for m in self.models), "pollinations": pollinations}
        in_time = deadline is None or self.expected["klein"] <= deadline
        order = ["klein", "schnell", "pollinations"] if in_time else ["schnell", "pollinations", "klein"]
        return [name for name in order if available[name]]

    def _pollinations_wait(self) -> float:
        """Seconds before a new anonymous Pollinations request could start (pacing plus the queue ahead of it)."""
        if self.settings.pollinations_key:
            return 0.0
        gap = max(0.0, 16.0 - (time.monotonic() - self._last_pollinations)) if self._last_pollinations else 0.0
        return gap + 16.0 * self._pollinations_queue

    def _observe(self, name: str, seconds: float) -> None:
        self.expected[name] = round(0.6 * self.expected[name] + 0.4 * seconds, 2)

    async def _klein(self, prompt: str, width: int, height: int, references: list[bytes]) -> Picture:
        model = next(m for m in self.models if "flux-2" in m)
        s = self.settings
        files: dict[str, tuple[str, bytes, str]] = {}
        for i, ref in enumerate(references[:2]):
            files[f"input_image_{i}"] = (f"ref{i}.jpg", ref, "image/jpeg")
        if files:
            prompt = (f"Keep the characters exactly as they look in the reference image"
                      f"{'s' if len(files) > 1 else ''}. {prompt}")
        else:
            files["_"] = ("", b"", "application/octet-stream")  # forces multipart, which this model requires
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.cloudflare.com/client/v4/accounts/{s.cloudflare_account_id}/ai/run/{model}",
                headers={"Authorization": f"Bearer {s.cloudflare_api_token}"},
                data={"prompt": prompt[:1900], "width": str(width), "height": str(height)}, files=files)
        self._check_cloud(resp)
        image = resp.json().get("result", {}).get("image")
        if not image:
            raise ImageError("empty result")
        return Picture(base64.b64decode(image), "flux-2-klein" + (" + refs" if references else ""))

    async def _schnell(self, prompt: str, width: int, height: int, references: list[bytes]) -> Picture:
        model = next(m for m in self.models if "flux-1" in m)
        s = self.settings
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.cloudflare.com/client/v4/accounts/{s.cloudflare_account_id}/ai/run/{model}",
                headers={"Authorization": f"Bearer {s.cloudflare_api_token}"},
                json={"prompt": prompt[:1900], "steps": 4})
        self._check_cloud(resp)
        image = resp.json().get("result", {}).get("image")
        if not image:
            raise ImageError("empty result")
        return Picture(base64.b64decode(image), "flux-1-schnell")

    def _check_cloud(self, resp: httpx.Response) -> None:
        """Cloudflare said no: remember why, so the next pictures go straight to a provider that can answer."""
        if resp.status_code == 429:
            if "4006" in resp.text or "daily free allocation" in resp.text:
                now = datetime.now(UTC)
                reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
                self._cloud_out_until = time.monotonic() + (reset - now).total_seconds()
                log.warning("Cloudflare's free daily picture allowance is used up; skipping it until 00:00 UTC "
                            "(%s). Pictures come from Pollinations or the browser's painter meanwhile.",
                            reset.astimezone().strftime("%H:%M local"))
                raise ImageError("Cloudflare daily allowance used up")
            self._cloud_out_until = time.monotonic() + 30.0
        resp.raise_for_status()

    async def _pollinations(self, prompt: str, width: int, height: int, references: list[bytes]) -> Picture:
        if time.monotonic() < self._paused_until:
            raise ImageError("paused after a rate limit")
        seed = int(hashlib.sha1(prompt.encode()).hexdigest()[:6], 16)
        key = self.settings.pollinations_key
        if key:
            url = (f"https://gen.pollinations.ai/image/{urllib.parse.quote(prompt[:900])}"
                   f"?model=flux&width={width}&height={height}&seed={seed}&safe=true")
            headers = {"Authorization": f"Bearer {key}"}
        else:
            url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt[:420])}"
                   f"?width={width}&height={height}&seed={seed}&nologo=true&safe=true&model=flux")
            headers = {}
        self._pollinations_queue += 1
        queued = True
        try:
            async with self._paced:
                self._pollinations_queue -= 1
                queued = False
                gap = 0.0 if key else 16.0 - (time.monotonic() - self._last_pollinations)  # anonymous: ~1 per 15 s
                if gap > 0:
                    await asyncio.sleep(gap)
                async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                self._last_pollinations = time.monotonic()
        finally:
            if queued:  # cancelled while still waiting for its turn
                self._pollinations_queue -= 1
        if resp.status_code in (402, 429):
            retry = resp.headers.get("retry-after", "")
            self._paused_until = time.monotonic() + (float(retry) if retry.isdigit() else 60.0)
        resp.raise_for_status()
        if not resp.headers.get("content-type", "").startswith("image"):
            raise ImageError("not an image")
        return Picture(resp.content, "pollinations", resp.headers["content-type"].split(";")[0])
