"""Run a whole story without a browser — the same story graph the web client uses.

Used by the terminal preview (``scripts/cli_story.py``), the MCP server and the evaluation harness.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import readability
from .agents.deps import Deps
from .agents.graphs import build_plan_graph
from .config import Settings
from .llm import LLMRouter
from .planner import shape_for
from .schemas import ChapterScript, ChoiceOption, StoryRequest

Chooser = Callable[[int, list[ChoiceOption]], str]


def first_choice(_: int, choices: list[ChoiceOption]) -> str:
    return choices[0].keyword


async def run_story(request: StoryRequest, settings: Settings, chooser: Chooser = first_choice,
                    on_event: Callable[[str, dict[str, Any]], None] | None = None,
                    router: Any = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    events: list[tuple[float, str, dict[str, Any]]] = []

    def emit(kind: str, data: dict[str, Any]) -> None:
        events.append((time.perf_counter() - t0, kind, data))
        if on_event:
            on_event(kind, data)

    deps = Deps(settings, router or LLMRouter(settings), emit)
    shape = shape_for(request.minutes, request.audience)
    plan = await build_plan_graph().ainvoke({"request": request, "shape": shape}, context=deps)
    plan_seconds = time.perf_counter() - t0
    screening = plan.get("screening")
    if screening and screening.verdict.decision == "refuse":
        return {"refused": True, "screening": screening, "events": events, "seconds": plan_seconds}
    chapters: list[ChapterScript] = list(plan["scripts"])
    decisions: list[str] = []
    if chapters and chapters[-1].choices and plan.get("branches"):
        keyword = chooser(len(chapters), chapters[-1].choices)
        chosen = next((c for c in chapters[-1].choices if c.keyword == keyword), chapters[-1].choices[0])
        decisions.append(chosen.label)
        chapters.append(plan["branches"].get(chosen.keyword) or next(iter(plan["branches"].values())))
    return {"refused": False, "screening": screening, "bible": plan["bible"], "cast": plan.get("cast"),
            "chapters": chapters, "branches": plan.get("branches", {}), "decisions": decisions,
            "grades": [readability.grade(" ".join(line.text for line in c.lines)) for c in chapters],
            "shape": shape, "events": events, "seconds": plan_seconds, "plan_seconds": plan_seconds,
            "opening_seconds": next((t for t, kind, _ in events if kind == "opening"), None)}
