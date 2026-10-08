"""Writer: writes one chapter at a time as an audio script with a shot list.

Writing chapter by chapter (instead of the whole story up front) is what makes the story interactive: every chapter
sees the listener's latest choice or spoken request, the running summary and the continuity ledger. Each chapter
also names the picture moments ("shots") so illustrations change exactly when the narration gets there.
"""

from __future__ import annotations

import re

from ..planner import StoryShape
from ..prompts import (
    AUDIENCE_RULES,
    ENDING_CHOICE,
    ENDING_FINAL,
    ENDING_HOOK,
    READING_LEVEL,
    STYLE_EXAMPLE,
    WRITER_SYSTEM,
    WRITER_USER,
)
from ..schemas import ChapterScript, ChoiceOption, Shot, StoryBible, StoryRequest
from .deps import Deps

STOP_WORDS = {"the", "a", "an", "to", "into", "through", "and", "or", "of", "with", "up", "down", "climb",
              "follow", "go", "take", "enter", "open", "ask", "stay", "run", "look", "find", "use", "try", "help"}


def keyword_for(option: str, taken: set[str]) -> str:
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", option)]
    for word in reversed(words):
        if word not in STOP_WORDS and len(word) > 2 and word not in taken:
            return word
    return f"option{len(taken) + 1}"


def story_so_far(summaries: list[str]) -> str:
    if not summaries:
        return "(this is the first chapter, right after the opening)"
    return "\n".join(f"Ch.{i}: {s}" for i, s in enumerate(summaries, start=1))


_SPEECH_VERBS = (r"said|says|smiled|whispered|asked|laughed|called|shouted|cried|replied|added|giggled|buzzed|"
                 r"sighed|squeaked|grinned|murmured|answered|exclaimed|chirped|hooted|beamed|nodded|gasped")
_ATTRIBUTED = re.compile(rf'^(?P<attr>(?P<who>[A-Z][\w\'-]*(?: [A-Z][\w\'-]*)?)[^"“”]{{0,40}}?\b(?:{_SPEECH_VERBS})\b'
                         rf'[^"“”]{{0,40}}?)[,:.]?\s*["“](?P<speech>[^"“”]{{2,}})["”]?\s*$')


def split_attributions(script: ChapterScript, bible: StoryBible) -> None:
    """Turn `Moss smiled, "The stone glows."` into a narrator line plus Moss speaking in Moss's own voice."""
    lines = []
    new_index = []  # where each original line ends up, so pictures stay on the same moments
    for line in script.lines:
        new_index.append(len(lines))
        match = _ATTRIBUTED.match(line.text)
        speaker = bible.resolve_speaker(match["who"]) if match else ""
        if match and bible.character(speaker):
            lines.append(line.model_copy(update={"speaker": "narrator", "text": match["attr"].strip(" ,") + ".",
                                                 "delivery": "neutral", "sfx": line.sfx}))
            lines.append(line.model_copy(update={"speaker": speaker, "text": match["speech"].strip(), "sfx": None}))
        else:
            lines.append(line)
    for shot in script.shots:
        if shot.line < len(new_index):
            shot.line = new_index[shot.line]
    script.lines = lines[:40]


def finalise_script(script: ChapterScript, bible: StoryBible, index: int, shape: StoryShape) -> ChapterScript:
    """Map speakers to known ids, align choices with the plan and make sure the shot list is usable."""
    plan = bible.chapters[index]
    for line in script.lines:
        line.speaker = bible.resolve_speaker(line.speaker)
    split_attributions(script, bible)
    if plan.choice is None:
        script.choices = []
    elif len(script.choices) < 2:  # writer forgot the options: derive them from the plan
        taken: set[str] = set()
        options = []
        for text in plan.choice.options[:3]:
            keyword = keyword_for(text, taken)
            taken.add(keyword)
            options.append(ChoiceOption(keyword=keyword, label=text[:60]))
        script.choices = options
    else:
        taken = set()
        for option in script.choices:
            if option.keyword in taken:
                option.keyword = keyword_for(option.label, taken)
            taken.add(option.keyword)
    known = {c.id for c in bible.characters}
    shots = []
    for shot in script.shots:
        shot.characters = [bible.resolve_speaker(c) for c in shot.characters]
        shot.characters = [c for c in shot.characters if c in known]
        shots.append(shot)
    wanted = shape.shots_for(index)  # pictures are a fixed budget per story (one per minute)
    if wanted and not shots:
        shots = [Shot(line=0, description=plan.summary)]
    shots.sort(key=lambda s: s.line)
    script.shots = shots[:wanted]
    return script


def shots_rule(count: int) -> str:
    if not count:
        return '"shots": [] — this chapter keeps the picture already on screen.'
    return (f'"shots": exactly {count} picture moment{"s" if count > 1 else ""} — the most striking moment(s) of the '
            'chapter. For each: "line" (index of the line where the picture appears; the first is 0), "description" '
            '(one sentence: who, where, doing what, light and mood) and "characters" (ids of characters visible).')


async def write_chapter(deps: Deps, request: StoryRequest, shape: StoryShape, bible: StoryBible, index: int,
                        summaries: list[str], facts: list[str], listener_note: str, lore: list[str],
                        revision_notes: str = "", patience: float = 0.0) -> ChapterScript:
    plan = bible.chapters[index]
    total = len(bible.chapters)
    final = index == total - 1
    ending = ENDING_FINAL if final else ENDING_CHOICE if plan.choice else ENDING_HOOK
    low, high = shape.lines_per_chapter
    lore_rule = ("- TRUE FACTS to weave in (at most one per chapter): show the fact through what happens or what "
                 "a character notices, in the story's own words — never recite it like a textbook. Facts: "
                 + " | ".join(lore)) if lore else ""
    system = WRITER_SYSTEM.format(
        reading_level=READING_LEVEL[request.audience], line_target=f"{low}-{high}",
        word_target=f"{int(shape.words_per_chapter * 0.9)}-{int(shape.words_per_chapter * 1.15)}",
        speaker_ids=", ".join(c.id for c in bible.characters), ending_rule=ending,
        shots_rule=shots_rule(shape.shots_for(index)), lore_rule=lore_rule,
        audience_rules=AUDIENCE_RULES[request.audience],
        style_example=STYLE_EXAMPLE[request.audience])
    choice_plan = (f"Planned choice: {plan.choice.question} Options: {' / '.join(plan.choice.options)}\n"
                   if plan.choice else "")
    user = WRITER_USER.format(
        bible=bible.outline(), index=index + 1, total=total, title=plan.title, beat=plan.beat, act=plan.act,
        tension=plan.tension, summary=plan.summary, propp=", ".join(plan.propp) or "-", choice_plan=choice_plan,
        story_so_far=story_so_far(summaries), facts="; ".join(facts) or "-",
        listener_note=f"LISTENER INPUT (follow it first): {listener_note}\n" if listener_note else "",
        revision_note=f"\nEDITOR NOTES ON YOUR PREVIOUS DRAFT — fix all of these:\n{revision_notes}"
        if revision_notes else "")
    script, _ = await deps.router.structured("writer", ChapterScript, [("system", system), ("human", user)],
                                             temperature=0.85, observer=deps, patience=patience)
    return finalise_script(script, bible, index, shape)
