"""Editor: the reflection step of the crew. Reviews every chapter before it is voiced.

Two passes, cheapest first:
1. deterministic checks — safety lexicon on every line, length, number of lines, reading level for the audience;
2. an LLM review — safety in context, clarity, continuity, plan adherence and "listenability".
A rejected draft goes back to the Writer once with concrete notes (generalising the Writer/Reviewer pair from my
Kahaani work). If the editor model is unavailable the draft passes on the deterministic checks alone.
"""

from __future__ import annotations

import logging

from .. import readability
from ..llm import LLMError
from ..planner import StoryShape
from ..prompts import AUDIENCE_RULES, EDITOR_SYSTEM, EDITOR_USER
from ..safety.guardian import output_issues
from ..schemas import ChapterScript, EditorReview, StoryBible, StoryRequest
from .deps import Deps
from .writer import story_so_far

log = logging.getLogger(__name__)


def automatic_checks(request: StoryRequest, shape: StoryShape, draft: ChapterScript) -> tuple[list[str], bool, float]:
    """Return (issues, safety_ok, reading grade) from checks that need no model."""
    text = " ".join(line.text for line in draft.lines)
    safety = output_issues(text, request.audience)
    issues = list(safety)
    minimum = int(shape.words_per_chapter * 0.6)
    if draft.word_count < minimum:
        issues.append(f"far too short ({draft.word_count} words) — write about {shape.words_per_chapter} words "
                      f"in {shape.lines_per_chapter[0]}-{shape.lines_per_chapter[1]} lines")
    if len(draft.lines) < 6:
        issues.append("too few lines for an audio scene — use more lines mixing narration and dialogue")
    grade = readability.grade(text)
    if grade > readability.MAX_GRADE[request.audience] + 1.5:
        issues.append(f"too hard to follow by ear (reading grade {grade:.1f}) — use shorter sentences and "
                      "simpler words")
    for shot in draft.shots:  # illustration prompts must be safe too
        if output_issues(shot.description, request.audience):
            issues.append("a picture description is unsuitable — keep pictures gentle")
            safety = [*safety, "picture"]
    return issues, not safety, grade


async def review_chapter(deps: Deps, request: StoryRequest, shape: StoryShape, bible: StoryBible, index: int,
                         draft: ChapterScript, summaries: list[str], listener_note: str,
                         run_llm: bool = True) -> tuple[EditorReview, float]:
    issues, safety_ok, grade = automatic_checks(request, shape, draft)
    if issues:
        return EditorReview(approved=False, safety_ok=safety_ok, issues=issues, notes="; ".join(issues)), grade
    if not run_llm:
        return EditorReview(), grade
    plan = bible.chapters[index]
    final = index == len(bible.chapters) - 1
    requirement = ("ends with a clear two-option choice for the listener" if plan.choice
                   else "resolves the story warmly without a choice" if final else "ends on a hook without a choice")
    system = EDITOR_SYSTEM.format(audience=request.audience, audience_rules=AUDIENCE_RULES[request.audience],
                                  choice_requirement=requirement)
    user = EDITOR_USER.format(
        bible=bible.outline(), index=index + 1, total=len(bible.chapters), title=plan.title, summary=plan.summary,
        story_so_far=story_so_far(summaries), listener=listener_note or "-", draft=draft.as_text(),
        choices=", ".join(f"{c.keyword} ({c.label})" for c in draft.choices) or "none")
    try:
        review, _ = await deps.router.structured("editor", EditorReview, [("system", system), ("human", user)],
                                                 temperature=0.1, observer=deps)
    except LLMError as exc:
        log.warning("Editor model unavailable, passing on automatic checks: %s", exc)
        return EditorReview(issues=["editor model unavailable — passed automatic checks"]), grade
    if not review.safety_ok:
        review.approved = False
    elif not review.approved and not review.issues and not review.notes.strip():
        review.approved = True  # a rejection without a single concrete issue is not actionable
    return review, grade
