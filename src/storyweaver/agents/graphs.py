"""StoryWeaver's LangGraph workflows. Stateless per request (serverless-friendly): the story travels with the
listener's browser.

STORY GRAPH (one request per story — about two model calls in total)

    START ─► precheck ─┬─(blocked by the lexicon)──────────────────────────────────────────► END
                       ├─► guardian ─────┐
                       └─► storyteller ──┴─► gate ─┬─(refuse)───────────────────────────────► END
                           (the whole story,       ├─(soften)─► retell ─┐
                            in parallel)           └─(allow)────────────┴─► editor ─┬─(clean)──────► release ─► END
                                                                             ▲      ├─(unsafe, 1st)─► retell
                                                                             │      └─(unsafe, 2nd)─► scrub ─► release
  * The Storyteller writes the whole story — opening, cast, every part and both endings of the choice — while the
    Guardian screens the request, so safety adds no waiting. Its draft is discarded if the Guardian refuses and
    rewritten from the safe version if the Guardian softens it.
  * The Editor checks every line and picture description deterministically (no model call); an unsafe draft is
    rewritten once with notes, and anything still unsafe is removed line by line.
  * ``release`` casts the voices and streams the story: narration starts at once and never waits again.

CHAPTER GRAPH (fallback only: rewrites a single chapter when no prepared script exists)

    START ─► writer ─► editor ─┬─(approved)──────────────────────► finalise ─► END
                ▲              ├─(rejected, first time)──► writer
                               └─(unsafe twice)─► safe_fallback ─► finalise ─► END
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .. import readability
from ..llm import LLMError
from ..media.voices import cast, cast_opening
from ..planner import StoryShape
from ..safety import lexicon
from ..safety.guardian import SAFE_IDEAS, LayerResult, Screening, output_issues, screen_request
from ..schemas import ChapterScript, EditorReview, GuardianVerdict, ScriptLine, Shot, StoryBible, StoryRequest
from ..shelf import shelf_story
from .deps import Deps
from .editor import review_chapter
from .storyteller import assemble, parts_needed, write_story
from .writer import write_chapter

MAX_REVISIONS = 1
# The longest a listener may wait for the Storyteller (normally ~2.5 s). Past it — free-tier limits exhausted —
# StoryWeaver tells one of its own hand-written stories instead of failing.
STORY_BUDGET_S = 12.0
VERDICT_TEXT = {"allow": "Safe for this audience ✓", "soften": "Softened for this audience",
                "refuse": "Not a story we can tell"}


# ================================================================ story graph
class PlanState(TypedDict, total=False):
    request: StoryRequest
    shape: StoryShape
    screening: Screening
    prompt: str  # the request that is actually told: the listener's, or the Guardian's softened version
    bible: StoryBible
    scripts: list[ChapterScript]  # the main path, in order
    branches: dict[str, ChapterScript]  # choice keyword -> the ending for that option
    story_error: str
    notes: str
    retells: int
    cast: dict[str, dict[str, Any]]
    shelf: bool  # a hand-written story was told because no model could deliver in time


async def precheck_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    request = state["request"]
    hits = lexicon.scan(request.prompt + " " + (request.hero_name or ""))
    if lexicon.worst(hits) != "block":
        return {"prompt": lexicon.redact_personal_data(request.prompt), "retells": 0}
    hit = next(h for h in hits if h.severity == "block")
    verdict = GuardianVerdict(decision="refuse", category=hit.category,
                              reason=f"The request asks for {hit.label}, which StoryWeaver never tells.",
                              alternatives=SAFE_IDEAS[request.audience])
    screening = Screening(verdict, [LayerResult("lexicon", "block", f"{hit.label}: “{hit.match}”")])
    deps.emit("safety", screening.as_event())
    deps.agent("guardian", "done", "refused by the safety lexicon")
    return {"screening": screening}


def precheck_route(state: PlanState) -> list[str] | str:
    return END if "screening" in state else ["guardian", "storyteller"]


async def guardian_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    deps.agent("guardian", "start", "Screening the request (lexicon · injection classifier · policy model)")
    screening = await screen_request(deps.router, state["request"], observer=deps)
    deps.emit("safety", screening.as_event())
    deps.agent("guardian", "done", VERDICT_TEXT[screening.verdict.decision])
    return {"screening": screening}


async def _tell(deps: Deps, state: PlanState, prompt: str, notes: str = "") -> dict[str, Any]:
    shape = state["shape"]
    deps.agent("storyteller", "start", f"Writing the whole story ({shape.describe()})")
    try:
        bible, scripts, branches = await asyncio.wait_for(
            write_story(deps, state["request"], prompt, shape, notes), STORY_BUDGET_S)
    except (TimeoutError, LLMError) as exc:
        deps.agent("storyteller", "done", "The free models are busy right now — telling one of StoryWeaver's own "
                                          "stories instead", fallback=True, reason=str(exc)[:200])
        bible, scripts, branches = assemble(shelf_story(state["request"].audience, parts_needed(shape)),
                                            state["request"], shape)
        return {"bible": bible, "scripts": scripts, "branches": branches, "prompt": prompt, "shelf": True}
    words = len(bible.opening.split()) + sum(s.word_count for s in [*scripts, *branches.values()])
    deps.agent("storyteller", "done", f"“{bible.title}” — {words} words"
               f"{', with both endings of the choice' if branches else ''}")
    return {"bible": bible, "scripts": scripts, "branches": branches, "prompt": prompt}


async def storyteller_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    try:
        # contact details never reach a model, even while the Guardian is still screening the request
        return await _tell(runtime.context, state, lexicon.redact_personal_data(state["request"].prompt))
    except Exception as exc:  # the gate asks for a retelling
        return {"story_error": str(exc)[:300]}


async def gate_node(state: PlanState) -> dict[str, Any]:
    return {}


def gate_route(state: PlanState) -> str:
    verdict = state["screening"].verdict
    if verdict.decision == "refuse":
        return END
    softened = verdict.decision == "soften" and verdict.safe_request.strip().lower() != state["prompt"].lower()
    return "retell" if softened or "bible" not in state else "editor"


async def retell_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    verdict = state["screening"].verdict
    softened = verdict.decision == "soften" and verdict.safe_request.strip()
    prompt = verdict.safe_request.strip() if softened and not state.get("notes") else state["prompt"]
    result = await _tell(runtime.context, state, prompt, state.get("notes", ""))
    return {**result, "retells": state.get("retells", 0) + 1}


def _issues(state: PlanState) -> list[str]:
    audience = state["request"].audience
    bible = state["bible"]
    texts = [bible.opening, bible.opening_shot]
    for script in [*state["scripts"], *state.get("branches", {}).values()]:
        texts += [line.text for line in script.lines] + [shot.description for shot in script.shots]
    return sorted({issue for text in texts for issue in output_issues(text, audience)})


async def check_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    """Deterministic checks of every line and picture description — instant, no model call."""
    deps = runtime.context
    deps.agent("editor", "start", "Checking every line and picture for this audience")
    issues = _issues(state)
    grade = readability.grade(" ".join(line.text for s in state["scripts"] for line in s.lines))
    deps.emit("review", {"chapter": 0, "grade": grade, "approved": not issues, "safety_ok": not issues,
                         "issues": issues, "notes": ""})
    deps.agent("editor", "done", "every line checked ✓" if not issues else f"{len(issues)} problem(s) found")
    return {"notes": "; ".join(issues)}


def check_route(state: PlanState) -> str:
    if not state.get("notes"):
        return "release"
    return "retell" if state.get("retells", 0) < 1 else "scrub"  # at most one rewrite: never a long wait


async def scrub_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    """Last resort: remove any line or picture that still fails the checks, so nothing unsuitable is voiced."""
    audience = state["request"].audience

    def clean(script: ChapterScript) -> ChapterScript:
        lines = [line for line in script.lines if not output_issues(line.text, audience)]
        if len(lines) < 3:
            lines = [ScriptLine(text=s.strip() + ".", delivery="warm") for s in script.summary.split(".") if s.strip()]
            lines += [ScriptLine(text="And so the adventure went on, gently and happily.", delivery="warm")] * 3
        shots = [s for s in script.shots if not output_issues(s.description, audience)]
        return script.model_copy(update={"lines": lines[:40], "shots": [s for s in shots if s.line < len(lines)]})

    runtime.context.agent("editor", "done", "removed the lines that still failed the checks")
    return {"scripts": [clean(s) for s in state["scripts"]],
            "branches": {k: clean(s) for k, s in state.get("branches", {}).items()}, "notes": ""}


async def release_node(state: PlanState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    bible, audience = state["bible"], state["request"].audience
    opening_voices = {sid: v.as_dict() for sid, v in cast_opening(bible, audience).items()}
    deps.emit("opening", {"opening": bible.model_dump(), "voices": opening_voices, "prompt": state["prompt"]})
    voices = {sid: v.as_dict() for sid, v in cast(bible, audience).items()}
    deps.agent("casting", "done", f"{len(voices) - 2} characters + narrator cast")
    return {"cast": voices}


def build_plan_graph():
    graph = StateGraph(PlanState, context_schema=Deps)
    for name, node in [("precheck", precheck_node), ("guardian", guardian_node), ("storyteller", storyteller_node),
                       ("gate", gate_node), ("retell", retell_node), ("editor", check_node),
                       ("scrub", scrub_node), ("release", release_node)]:
        graph.add_node(name, node)
    graph.add_edge(START, "precheck")
    graph.add_conditional_edges("precheck", precheck_route, ["guardian", "storyteller", END])
    graph.add_edge(["guardian", "storyteller"], "gate")
    graph.add_conditional_edges("gate", gate_route, ["retell", "editor", END])
    graph.add_edge("retell", "editor")
    graph.add_conditional_edges("editor", check_route, ["release", "retell", "scrub"])
    graph.add_edge("scrub", "release")
    graph.add_edge("release", END)
    return graph.compile()


# ================================================================ chapter graph
class ChapterState(TypedDict, total=False):
    request: StoryRequest
    shape: StoryShape
    bible: StoryBible
    index: int
    summaries: list[str]
    facts: list[str]
    listener_note: str
    lore: list[str]
    patience: float
    draft: ChapterScript | None
    review: EditorReview | None
    grade: float
    revisions: int
    fallback: bool


async def writer_node(state: ChapterState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    review = state.get("review")
    revising = bool(review and not review.approved)
    deps.agent("writer", "start", f"Writing chapter {state['index'] + 1}" + (" (revision)" if revising else ""))
    draft = await write_chapter(
        deps, state["request"], state["shape"], state["bible"], state["index"], state.get("summaries", []),
        state.get("facts", []), state.get("listener_note", ""), state.get("lore", []),
        revision_notes=(review.notes or "; ".join(review.issues)) if revising and review else "",
        patience=state.get("patience", 0.0))
    deps.agent("writer", "done", f"{draft.word_count} words · {len(draft.lines)} lines · {len(draft.shots)} pictures")
    return {"draft": draft}


async def editor_node(state: ChapterState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    deps.agent("editor", "start", f"Reviewing chapter {state['index'] + 1}")
    review, grade = await review_chapter(deps, state["request"], state["shape"], state["bible"], state["index"],
                                         state["draft"], state.get("summaries", []), state.get("listener_note", ""))
    deps.emit("review", {"chapter": state["index"] + 1, "grade": grade, **review.model_dump()})
    deps.agent("editor", "done", "approved" if review.approved else f"revision requested: {'; '.join(review.issues)}")
    return {"review": review, "grade": grade, "revisions": state.get("revisions", 0) + (0 if review.approved else 1)}


def editor_route(state: ChapterState) -> str:
    review = state["review"]
    if review.approved:
        return "finalise"
    if state.get("revisions", 0) <= MAX_REVISIONS:
        return "writer"
    return "finalise" if review.safety_ok else "safe_fallback"


async def safe_fallback_node(state: ChapterState, runtime: Runtime[Deps]) -> dict[str, Any]:
    """Never voice a draft that failed safety twice: tell the planned beat plainly, narrator only."""
    plan = state["bible"].chapters[state["index"]]
    lines = [ScriptLine(text=sentence.strip() + ".", delivery="warm")
             for sentence in plan.summary.split(".") if sentence.strip()]
    lines += [ScriptLine(text="And so the adventure carried on, one gentle step at a time.", delivery="warm")
              ] * max(0, 3 - len(lines))
    shots = [Shot(line=0, description=plan.summary)] if state["shape"].shots_for(state["index"]) else []
    draft = ChapterScript(title=plan.title, lines=lines, shots=shots, summary=plan.summary)
    runtime.context.agent("editor", "done", "used the safe fallback chapter")
    return {"draft": draft, "fallback": True}


async def finalise_node(state: ChapterState) -> dict[str, Any]:
    draft = state["draft"]
    return {"grade": readability.grade(" ".join(line.text for line in draft.lines))}


def build_chapter_graph():
    graph = StateGraph(ChapterState, context_schema=Deps)
    for name, node in [("writer", writer_node), ("editor", editor_node), ("safe_fallback", safe_fallback_node),
                       ("finalise", finalise_node)]:
        graph.add_node(name, node)
    graph.add_edge(START, "writer")
    graph.add_edge("writer", "editor")
    graph.add_conditional_edges("editor", editor_route, ["finalise", "writer", "safe_fallback"])
    graph.add_edge("safe_fallback", "finalise")
    graph.add_edge("finalise", END)
    return graph.compile()
