"""Model routing: every agent role has an ordered chain of (provider, model) candidates.

Why a custom router instead of a single model?
* Free tiers have small per-model rate limits — spreading roles across models keeps a story flowing.
* When a call fails (rate limit, outage, malformed output) the router falls through to the next candidate
  and reports what happened, so the UI's crew panel can show it.
* It remembers rate limits: a model that answered "429, try again in 7 s" is skipped until then instead of
  being hit again — and a *lookahead* call that is not needed for a while (``patience``) waits for its preferred
  model rather than falling back to a weaker one.
* Structured outputs are validated with the lenient Pydantic schemas in ``schemas.py``; if a model returns
  JSON that still does not validate, it gets one chance to repair it before the next candidate is tried.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class CallInfo:
    role: str
    provider: str
    model: str
    ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    fallbacks: list[str] = field(default_factory=list)

    def as_event(self) -> dict[str, Any]:
        return {"role": self.role, "provider": self.provider, "model": self.model, "ms": self.ms,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "fallbacks": self.fallbacks}


class LLMError(RuntimeError):
    def __init__(self, role: str, errors: list[str]):
        super().__init__(f"All models failed for role '{role}': {'; '.join(errors) or 'no models configured'}")
        self.role = role
        self.errors = errors


class Observer(Protocol):
    """Receives call telemetry and back-off notices (implemented by ``agents.deps.Deps``)."""

    def trace(self, info: CallInfo) -> None: ...
    def waiting(self, role: str, seconds: float, planned: bool = False) -> None: ...


# Output budgets per role. Groq counts the *requested* completion budget against the free tier's tokens-per-minute
# window (8K for most models), so budgets are sized to what each role really writes (incl. brief reasoning) —
# generous budgets would make two parallel chapter calls exceed the window on their own.
ROLE_MAX_TOKENS = {"guardian": 600, "storyteller": 3600, "writer": 2400,
                   "editor": 700, "interpreter": 400, "baseline": 3000}
# Seconds one model may take for a role (including one repair round) before the next model is tried: a hung free
# endpoint must not stall an agent on the critical path.
ROLE_TIMEOUT_S = {"guardian": 12.0, "storyteller": 30.0, "writer": 35.0,
                  "editor": 15.0, "interpreter": 4.0, "baseline": 60.0}
# Seconds to wait before each pass over a role's chain when every model was rate-limited/unavailable.
BACKOFF_S = (0.0, 6.0, 15.0, 30.0)
TRANSIENT = ("rate-limited", "unavailable", "timeout")
COOLDOWN_S = {"rate-limited": 12.0, "unavailable": 8.0}  # when the provider gives no "try again in" hint


def retry_after(exc: BaseException) -> float | None:
    """Parse provider hints such as 'Please try again in 7.66s' / 'in 1m2.5s' / 'in 450ms' / 'retry in 3s'."""
    match = re.search(r"(?:try again|retry) in (?:(\d+)m)?([\d.]+)(ms|s)", str(exc))
    if not match:
        return None
    minutes = float(match.group(1) or 0)
    value = float(match.group(2))
    return minutes * 60 + (value / 1000 if match.group(3) == "ms" else value)


def describe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "429" in text or "rate limit" in lowered or "resource_exhausted" in lowered or "quota" in lowered:
        return "rate-limited"
    if "503" in text or "unavailable" in lowered or "overloaded" in lowered or "high demand" in lowered:
        return "unavailable"
    if isinstance(exc, asyncio.TimeoutError | TimeoutError) or "timeout" in lowered:
        return "timeout"
    if isinstance(exc, ValidationError | json.JSONDecodeError):
        return "invalid-output"
    return text[:160]


def extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model reply (handles ```json fences and chatter)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    return json.loads(candidate[start:end + 1])


def _usage(message: Any) -> tuple[int | None, int | None]:
    usage = getattr(message, "usage_metadata", None) or {}
    return usage.get("input_tokens"), usage.get("output_tokens")


def _content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):  # some providers return content blocks
        return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class LLMRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[tuple[Any, ...], BaseChatModel] = {}
        self._http: dict[int, httpx.AsyncClient] = {}  # one keep-alive pool per event loop
        self._cooldown: dict[str, float] = {}  # model -> monotonic time it may be called again

    # -- start-up -------------------------------------------------------------------------------------
    @staticmethod
    def warmup() -> None:
        """Import the provider SDKs up front (blocking — run it in a thread at start-up).

        Imported lazily they take 3-4 s each on a modest laptop, and an import inside a request freezes the event
        loop: the first story — or the first fallback to Gemini, mid-story — would stall every other request.
        """
        started = time.perf_counter()
        import langchain_google_genai  # noqa: F401
        import langchain_groq  # noqa: F401
        log.info("Model providers ready in %.1f s", time.perf_counter() - started)

    def http(self) -> httpx.AsyncClient | None:
        """A shared keep-alive connection pool for the Groq API (saves a TLS handshake on most calls)."""
        loop = _running_loop()
        if loop is None:
            return None
        client = self._http.get(id(loop))
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=self.settings.llm_timeout_s,
                                       limits=httpx.Limits(max_connections=32, keepalive_expiry=90))
            self._http[id(loop)] = client
        return client

    async def preconnect(self) -> None:
        """Open the connection to Groq before the first story is requested (called when the page loads)."""
        client = self.http()
        if client is None or not self.settings.groq_api_key:
            return
        with contextlib.suppress(httpx.HTTPError):
            await client.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {self.settings.groq_api_key}"}, timeout=5)

    # -- model construction ---------------------------------------------------------------------------
    def chat_model(self, provider: str, model: str, temperature: float = 0.7,
                   max_tokens: int | None = None) -> BaseChatModel:
        http = self.http() if provider == "groq" else None
        key = (provider, model, temperature, max_tokens, id(http))
        if key in self._cache:
            return self._cache[key]
        if provider == "groq":
            from langchain_groq import ChatGroq

            kwargs: dict[str, Any] = {"http_async_client": http} if http else {}
            if model.startswith("openai/gpt-oss"):
                kwargs["reasoning_effort"] = "low"  # faster and cheaper; creative tasks gain little
            chat: BaseChatModel = ChatGroq(
                model=model, api_key=self.settings.groq_api_key, temperature=temperature,
                max_tokens=max_tokens, max_retries=0, timeout=self.settings.llm_timeout_s, **kwargs)
        elif provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            chat = ChatGoogleGenerativeAI(
                model=model, google_api_key=self.settings.gemini_api_key, temperature=temperature,
                max_output_tokens=max_tokens, max_retries=0, timeout=self.settings.llm_timeout_s)
        else:
            raise ValueError(f"Unknown provider '{provider}'")
        self._cache[key] = chat
        return chat

    def chain(self, role: str) -> list[tuple[str, str]]:
        return self.settings.route(role)

    def cooldown_left(self, model: str) -> float:
        return max(0.0, self._cooldown.get(model, 0.0) - time.monotonic())

    # -- structured output ----------------------------------------------------------------------------
    async def structured(self, role: str, schema: type[T], messages: Sequence[BaseMessage | tuple[str, str]],
                         *, temperature: float = 0.7, observer: Observer | None = None,
                         patience: float = 0.0, max_tokens: int | None = None) -> tuple[T, CallInfo]:
        """``max_tokens`` overrides the role's budget for a smaller job (Groq counts the requested maximum against
        its per-minute limit, so asking for no more than needed keeps the next call from being rate-limited)."""
        async def attempt(provider: str, model: str) -> tuple[T, tuple[int | None, int | None]]:
            return await self._structured_once(provider, model, schema, list(messages), temperature,
                                               max_tokens or ROLE_MAX_TOKENS.get(role))
        return await self._with_fallbacks(role, attempt, observer, patience)

    async def _with_fallbacks(self, role: str, attempt: Callable[[str, str], Awaitable[tuple[Any, Any]]],
                              observer: Observer | None, patience: float = 0.0) -> tuple[Any, CallInfo]:
        """Try each model of the role's chain, skipping (or, with patience, waiting out) rate-limited ones;
        if all failed transiently, back off and go round again."""
        errors: list[str] = []
        deadline = time.monotonic() + max(0.0, patience)
        chain = self.chain(role)
        for pass_no, pause in enumerate(BACKOFF_S):
            if pass_no:
                soonest = min((self.cooldown_left(m) for _, m in chain), default=0.0)
                wait = min(max(pause, soonest), 30.0)
                if observer:
                    observer.waiting(role, wait)
                await asyncio.sleep(wait)
            transient = False
            for provider, model in chain:
                for _ in range(2):  # a second try only after waiting out this model's cool-down
                    wait = self.cooldown_left(model)
                    if wait > 0:
                        if wait > deadline - time.monotonic():
                            transient = True
                            errors.append(f"{model} cooling down")
                            break
                        if observer:
                            observer.waiting(role, wait, planned=True)
                        await asyncio.sleep(wait)
                    started = time.perf_counter()
                    try:
                        result, usage = await asyncio.wait_for(
                            attempt(provider, model), timeout=ROLE_TIMEOUT_S.get(role, self.settings.llm_timeout_s))
                    except Exception as exc:
                        reason = describe_error(exc)
                        detail = f" — {str(exc)[:200]}" if reason == "rate-limited" else ""
                        log.warning("%s: %s/%s failed (%s)%s", role, provider, model, reason, detail)
                        errors.append(f"{model} {reason}")
                        transient = transient or reason in TRANSIENT
                        if reason in COOLDOWN_S:
                            self._cooldown[model] = time.monotonic() + (retry_after(exc) or COOLDOWN_S[reason])
                            continue
                        break
                    info = CallInfo(role, provider, model, int((time.perf_counter() - started) * 1000),
                                    *usage, fallbacks=errors)
                    if observer:
                        observer.trace(info)
                    return result, info
            if not transient:
                break
        raise LLMError(role, errors)

    async def _structured_once(self, provider: str, model: str, schema: type[T], messages: list[Any],
                               temperature: float, max_tokens: int | None
                               ) -> tuple[T, tuple[int | None, int | None]]:
        chat = self.chat_model(provider, model, temperature, max_tokens)
        runnable = chat.with_structured_output(schema, method="json_schema", include_raw=True)
        out = await runnable.ainvoke(messages)
        raw = out.get("raw")
        usage = _usage(raw)
        if out.get("parsed") is not None:
            return out["parsed"], usage
        # Lenient second chance: parse the raw text ourselves (validators coerce near-misses).
        raw_text = _content(raw)
        try:
            return schema.model_validate(extract_json(raw_text)), usage
        except (ValidationError, json.JSONDecodeError) as exc:
            error = exc
        # One repair round with the validation error fed back to the same model.
        repair = [*messages, AIMessage(content=raw_text[:6000]),
                  HumanMessage(content=f"That JSON did not match the required schema:\n{str(error)[:1500]}\n"
                                       "Return only the corrected JSON object.")]
        out = await runnable.ainvoke(repair)
        if out.get("parsed") is not None:
            return out["parsed"], usage
        return schema.model_validate(extract_json(_content(out.get("raw")))), usage

    # -- plain text -----------------------------------------------------------------------------------
    async def text(self, role: str, messages: Sequence[BaseMessage | tuple[str, str]], *,
                   temperature: float = 0.7, observer: Observer | None = None) -> tuple[str, CallInfo]:
        async def attempt(provider: str, model: str) -> tuple[str, tuple[int | None, int | None]]:
            chat = self.chat_model(provider, model, temperature, ROLE_MAX_TOKENS.get(role))
            reply = await chat.ainvoke(list(messages))
            return _content(reply), _usage(reply)
        return await self._with_fallbacks(role, attempt, observer)
