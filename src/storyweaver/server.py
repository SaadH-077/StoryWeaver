"""FastAPI application — a *stateless* API plus the static web client.

Every endpoint is an independent, short request; the story so far travels with the listener's browser. That makes
StoryWeaver fast (the browser prepares the next chapter while the current one plays) and deployable as serverless
functions (e.g. Vercel), with no session state, disk writes or long-lived connections.

    POST /api/plan       NDJSON stream: safety layers, then the whole story — bible, cast, every part and both
                         endings of the choice (story graph; about two model calls)
    POST /api/revise     a listener's spoken wish: the story from the next sentence on, rewritten in one call
    POST /api/chapter    NDJSON stream: writer/editor progress, the chapter script         (chapter graph)
    POST /api/tts        one line of speech (studio or cloud voice) as WAV
    POST /api/image      one illustration (scene or portrait, optional character references) as JPEG
    POST /api/listen     push-to-talk audio -> transcript -> intent (choice / steer / question)
    POST /api/interpret  typed text -> intent
    GET  /api/health, /api/config
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import mimetypes
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, readability
from .agents.deps import Deps
from .agents.graphs import build_chapter_graph, build_plan_graph
from .agents.interpreter import interpret
from .agents.storyteller import revise_story
from .config import SERVERLESS, Settings, get_settings
from .llm import LLMError, LLMRouter
from .media.images import ImageError, ImageService, compose_prompt
from .media.stt import TranscriptionError, transcribe
from .media.tts import TTSError, TTSService
from .planner import LENGTHS, shape_for
from .safety.guardian import output_issues, screen_snippet
from .schemas import ChoiceOption, StoryBible, StoryRequest

log = logging.getLogger("storyweaver")
MAX_AUDIO_BYTES = 5 * 1024 * 1024
REVISE_BUDGET_S = 25.0  # a spoken wish: past this, the story has moved on and continues as written

# Windows' registry often maps .js to "text/plain", which browsers refuse for ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

EXAMPLES = [
    {"emoji": "🦔", "text": "A little hedgehog who is afraid of the dark"},
    {"emoji": "🌆", "text": "An unexpected journey through a futuristic city"},
    {"emoji": "🗼", "text": "A lighthouse keeper who receives letters from the future"},
    {"emoji": "🐉", "text": "A dragon who opens a bakery"},
    {"emoji": "🌙", "text": "The night the moon forgot to rise"},
    {"emoji": "🐱", "text": "A detective cat and the mystery of the missing socks"},
    {"emoji": "☁️", "text": "A cloud who wants to learn how to rain"},
    {"emoji": "🤖", "text": "A tiny robot who repairs broken dreams"},
    {"emoji": "🐧", "text": "The penguin who wanted to fly to the moon"},
    {"emoji": "📚", "text": "A library where the books whisper at night"},
    {"emoji": "🐌", "text": "A snail who enters the great forest race"},
    {"emoji": "⭐", "text": "A lost star who lands in a fishing village"},
]


# ---------------------------------------------------------------- request models
class ChapterRequest(BaseModel):
    request: StoryRequest
    bible: StoryBible
    index: int = Field(ge=0, le=3)
    summaries: list[str] = Field(default_factory=list, max_length=8)
    facts: list[str] = Field(default_factory=list, max_length=24)
    listener_note: str = Field(default="", max_length=300)
    lore: list[str] = Field(default_factory=list, max_length=6)
    # Seconds until the listener needs this chapter (the browser prepares chapters ahead). With time to spare, the
    # Writer waits for its preferred model instead of falling back when the free tier is momentarily busy.
    deadline_s: float = Field(default=0.0, ge=0, le=900)


class ReviseRequest(BaseModel):
    request: StoryRequest
    bible: StoryBible
    told: str = Field(default="", max_length=8000)  # what the listener has heard so far (and will, meanwhile)
    wish: str = Field(min_length=1, max_length=300)
    part: int = Field(default=0, ge=0, le=1)  # the part being told: 0 = the opening or the first part, 1 = an ending
    fresh: bool = True  # that part has not started yet (rewrite it whole) — otherwise continue mid-part
    remaining_words: int = Field(default=0, ge=0, le=800)  # how much of the current part was still to come
    chosen: str = Field(default="", max_length=80)  # the option already picked, if any


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=700)
    voice: dict[str, Any] = Field(default_factory=dict)
    delivery: str = "neutral"
    engine: Literal["neural", "studio", "cloud"] = "neural"


class ImageRequest(BaseModel):
    description: str = Field(min_length=3, max_length=700)
    style: str = Field(default="storybook illustration", max_length=300)
    looks: list[str] = Field(default_factory=list, max_length=4)
    kind: Literal["scene", "portrait"] = "scene"
    references: list[str] = Field(default_factory=list, max_length=2)  # base64 JPEGs (character portraits)
    width: int = Field(default=768, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    deadline_s: float | None = Field(default=None, ge=0, le=900)  # seconds until the picture is shown


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    audience: str = "family"
    choices: list[ChoiceOption] = Field(default_factory=list, max_length=3)
    summaries: list[str] = Field(default_factory=list, max_length=8)


# ---------------------------------------------------------------- services
class Services:
    def __init__(self, settings: Settings, router: Any = None, tts: Any = None, images: Any = None):
        self.settings = settings
        self.router = router or LLMRouter(settings)
        self.tts = tts or TTSService(settings)
        self.images = images or ImageService(settings)
        self.plan_graph = build_plan_graph()
        self.chapter_graph = build_chapter_graph()


def chapter_result(index: int, script: Any) -> dict[str, Any]:
    """One part of the story in the shape the browser plays."""
    return {"index": index, "script": script.model_dump(), "words": script.word_count,
            "grade": round(readability.grade(" ".join(line.text for line in script.lines)), 1),
            "revisions": 0, "fallback": False}


def ndjson_run(graph: Any, state: dict[str, Any], services: Services, finish: Any) -> StreamingResponse:
    """Run a graph, streaming every agent/tool/model event as one JSON line, then the result line."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    started = time.perf_counter()

    def emit(kind: str, data: dict[str, Any]) -> None:
        queue.put_nowait({"type": kind, "t": int((time.perf_counter() - started) * 1000), **data})

    async def runner() -> None:
        try:
            result = await graph.ainvoke(state, context=Deps(services.settings, services.router, emit))
            emit("result", finish(result))
        except Exception as exc:
            log.exception("Graph failed")
            busy = "rate" in str(exc).lower() or "All models failed" in str(exc)
            emit("error", {"message": "The storytellers are busy right now (free-tier limits) — please try again "
                                      "in a minute." if busy else f"Something went wrong: {str(exc)[:200]}"})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(runner())

    async def stream():
        while (item := await queue.get()) is not None:
            yield json.dumps(item, ensure_ascii=False, default=str) + "\n"
        await task

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()

    background: set[asyncio.Task[Any]] = set()

    def spawn(coro: Any) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services or Services(settings)
        if services is None:
            spawn(asyncio.to_thread(LLMRouter.warmup))  # provider SDKs load while the page opens
            if settings.studio_warmup and not SERVERLESS and app.state.services.tts.studio.available:
                spawn(app.state.services.tts.studio.warmup())
        yield
        for task in list(background):
            task.cancel()

    app = FastAPI(title="StoryWeaver", version=__version__, lifespan=lifespan)

    def svc(request: Request) -> Services:
        return request.app.state.services

    # ------------------------------------------------------------ info
    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        s = svc(request)
        if hasattr(s.router, "preconnect"):
            spawn(s.router.preconnect())  # the page just opened: get the model connection ready for its first story
        return {"ok": bool(s.settings.groq_api_key), "version": __version__, "serverless": SERVERLESS,
                "llm": {"groq": bool(s.settings.groq_api_key), "gemini": bool(s.settings.gemini_api_key)},
                "voices": s.tts.engines(), "images": s.images.providers,
                "voice_input": bool(s.settings.groq_api_key)}

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        lengths = []
        for minutes in LENGTHS:
            shape = shape_for(minutes)
            lengths.append({"minutes": minutes, "chapters": shape.chapters, "choices": len(shape.choice_after),
                            "choice_after": shape.choice_after, "pictures": shape.pictures})
        return {"examples": EXAMPLES, "lengths": lengths}

    # ------------------------------------------------------------ story
    @app.post("/api/plan")
    async def plan(body: StoryRequest, request: Request) -> StreamingResponse:
        s = svc(request)
        if not s.settings.groq_api_key:
            raise HTTPException(503, "GROQ_API_KEY is not configured — see README › Quick start.")
        shape = shape_for(body.minutes, body.audience)

        def finish(state: dict[str, Any]) -> dict[str, Any]:
            screening = state.get("screening")
            refused = bool(screening and screening.verdict.decision == "refuse")
            bible = state.get("bible")
            told = not refused and bible is not None
            return {"refused": refused, "safety": screening.as_event() if screening else None,
                    "request": body.model_dump(), "shape": {**asdict(shape), "describe": shape.describe(),
                                                            "pictures": shape.pictures},
                    "bible": bible.model_dump() if told else None,
                    "cast": state.get("cast") if told else None,
                    "chapters": [chapter_result(i, s) for i, s in enumerate(state.get("scripts", []))] if told else [],
                    "branches": {k: chapter_result(1, s) for k, s in state.get("branches", {}).items()} if told else {},
                    "shelf": bool(state.get("shelf"))}

        return ndjson_run(s.plan_graph, {"request": body, "shape": shape}, s, finish)

    @app.post("/api/revise")
    async def revise(body: ReviseRequest, request: Request) -> dict[str, Any]:
        s = svc(request)
        ok, _ = screen_snippet(body.wish)
        if not ok:
            raise HTTPException(422, "That wish isn't something StoryWeaver can weave in.")
        shape = shape_for(body.request.minutes, body.request.audience)
        deps = Deps(s.settings, s.router)
        try:  # a wish is only useful while the story is still playing: never keep working on it for long
            scripts, question, newcomers = await asyncio.wait_for(
                revise_story(deps, body.request, shape, body.bible, body.told, body.wish, body.part, body.chosen,
                             body.fresh, body.remaining_words), REVISE_BUDGET_S)
        except (TimeoutError, LLMError) as exc:
            raise HTTPException(503, "The storytellers are busy right now; the story continues as it was.") from exc
        issues = [i for _, sc in scripts for line in sc.lines
                  for i in output_issues(line.text, body.request.audience)]
        if issues:
            raise HTTPException(422, "The rewrite did not pass the safety checks; the story continues as it was.")
        newcomers = [c for c in newcomers if screen_snippet(f"{c.name} {c.description}")[0]]
        return {"part": body.part, "fresh": body.fresh, "question": question,
                "characters": [c.model_dump() for c in newcomers],
                "chapters": [chapter_result(index, sc) for index, sc in scripts]}

    @app.post("/api/chapter")
    async def chapter(body: ChapterRequest, request: Request) -> StreamingResponse:
        s = svc(request)
        if body.index >= len(body.bible.chapters):
            raise HTTPException(422, "No such chapter in this story.")
        note = body.listener_note if screen_snippet(body.listener_note)[0] else ""
        shape = shape_for(body.request.minutes, body.request.audience)
        state = {"request": body.request, "shape": shape, "bible": body.bible, "index": body.index,
                 "summaries": body.summaries, "facts": body.facts, "listener_note": note, "lore": body.lore,
                 # leave ~15 s for writing, reviewing and the first picture
                 "patience": min(max(body.deadline_s - 15.0, 0.0), 45.0)}

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            draft = result["draft"]
            return {"index": body.index, "script": draft.model_dump(), "grade": result.get("grade"),
                    "revisions": result.get("revisions", 0), "fallback": bool(result.get("fallback")),
                    "words": draft.word_count}

        return ndjson_run(s.chapter_graph, state, s, finish)

    # ------------------------------------------------------------ media
    @app.post("/api/tts")
    async def tts(body: SpeechRequest, request: Request) -> Response:
        if not screen_snippet(body.text)[0]:
            raise HTTPException(422, "Refusing to voice unsafe text.")
        try:
            speech = await svc(request).tts.speak(body.text, body.voice, body.delivery, body.engine)
        except TTSError as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(speech.audio, media_type=speech.mime,
                        headers={"X-Duration": f"{speech.duration:.3f}", "X-Engine": speech.engine,
                                 "X-Voice": speech.voice, "Cache-Control": "public, max-age=86400"})

    @app.post("/api/image")
    async def image(body: ImageRequest, request: Request) -> Response:
        try:
            references = [base64.b64decode(r.split(",")[-1], validate=True) for r in body.references]
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "Invalid reference image.") from exc
        prompt = compose_prompt(body.description, body.style, body.looks, body.kind)
        try:
            picture = await svc(request).images.generate(prompt, body.width, body.height, references,
                                                         body.deadline_s,
                                                         shelf=body.description if body.kind == "scene" else None)
        except ImageError as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(picture.data, media_type=picture.mime,
                        headers={"X-Provider": picture.provider, "Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------------ listener
    @app.post("/api/interpret")
    async def interpret_text(body: InterpretRequest, request: Request) -> dict[str, Any]:
        s = svc(request)
        intent = await interpret(Deps(s.settings, s.router), body.text, body.choices, body.summaries, body.audience)
        return intent.model_dump()

    @app.post("/api/listen")
    async def listen(request: Request, audio: Annotated[UploadFile, File()],
                     context: Annotated[str, Form()] = "{}") -> dict[str, Any]:
        s = svc(request)
        data = await audio.read()
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording too long.")
        try:
            text = await transcribe(data, audio.filename or "speech.webm", audio.content_type or "audio/webm",
                                    s.settings)
        except TranscriptionError as exc:
            raise HTTPException(502, str(exc)) from exc
        if not text:
            return {"transcript": "", "intent": {"kind": "unclear"}}
        try:
            ctx = InterpretRequest.model_validate({**json.loads(context or "{}"), "text": text[:300]})
        except Exception:
            ctx = InterpretRequest(text=text[:300])
        intent = await interpret(Deps(s.settings, s.router), ctx.text, ctx.choices, ctx.summaries, ctx.audience)
        return {"transcript": text, "intent": intent.model_dump()}

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error")
        return JSONResponse({"detail": "Internal error — see the server log."}, status_code=500)

    # ------------------------------------------------------------ static client (served by the CDN on Vercel)
    if settings.public_dir.exists():
        app.mount("/", StaticFiles(directory=settings.public_dir, html=True), name="public")
    return app


if SERVERLESS:  # no lifespan warm-up on serverless platforms: load the providers during the cold start instead
    LLMRouter.warmup()
app = create_app()
