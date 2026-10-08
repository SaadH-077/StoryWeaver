"""Storyteller: writes the WHOLE story in one model call — opening, cast, every part and both endings of the choice.

Why one call? The story is told without a single pause: when narration starts, everything — including both paths of
the listener's choice — is already written and checked. It is also the cheapest design on free tiers (about two model
calls per story: this one and the Guardian's, which run in parallel). Structure stays explicit: the planner fixes the
Story Spine beats, the choice and the picture budget, and the result is assembled here into a story bible plus one
script per part, which the deterministic Editor then checks line by line.

A listener's spoken wish rewrites the story from the next sentence on (``revise_story``): the rest of the part being
told, the choice and both endings — in the background, while the story keeps playing. If that fails, the original
story simply continues.
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import cache

from pydantic import Field, create_model

from ..planner import StoryShape
from ..prompts import AUDIENCE_RULES, READING_LEVEL, REVISE_USER, STORY_SYSTEM, STORY_USER, STYLE_EXAMPLE
from ..schemas import (
    ChapterPlan,
    ChapterScript,
    ChoiceOption,
    ChoiceSeed,
    DraftPart,
    NewCharacter,
    ScriptLine,
    StoryBible,
    StoryDraft,
    StoryPlan,
    StoryRemainder,
    StoryRequest,
    slugify,
)
from .deps import Deps
from .writer import STOP_WORDS, finalise_script, keyword_for, shots_rule


def _part_rule(words: int, lines: tuple[int, int], shots: int) -> str:
    return f"about {words} words in {lines[0]}-{lines[1]} lines; {shots_rule(shots)}"


ENDING = ("follows the listener's choice within its first two lines, solves the problem with the detail planted "
          "earlier and ends warmly (\"And ever since then…\"); \"choices\": []")


def structure(shape: StoryShape, start: int = 0, chosen: str = "") -> str:
    """The STRUCTURE block of the prompt, for the parts from ``start`` on (``chosen``: the option already picked)."""
    words, lines = shape.words_per_chapter, shape.lines_per_chapter
    if not shape.choice_after:
        return ('"parts": exactly 1 — the whole adventure after the opening ("But one day… Because of that… Until '
                f'finally… And ever since then…"), {_part_rule(words, lines, shape.shots_for(0))} It ends warmly. '
                '"choices": [], "question": "".')
    ending = ENDING
    if start == 0:
        return (f'"parts": exactly 3.\n- parts[0] — "But one day… Because of that…": the problem appears and grows; '
                f'{_part_rule(words, lines, shape.shots_for(0))} It ends with the narrator asking the listener what '
                'should happen, naming both options in one or two simple sentences; put that question in "question" '
                'and the two options in parts[0].choices.\n'
                '- parts[1] — the ending if the listener picks the FIRST option: '
                f'{_part_rule(words, lines, shape.shots_for(1))} It {ending}.\n'
                '- parts[2] — the ending if the listener picks the SECOND option: same rules.')
    if chosen:
        return (f'"parts": exactly 1 — the ending after the listener chose "{chosen}": '
                f'{_part_rule(words, lines, shape.shots_for(1))} It {ending}.')
    return (f'"parts": exactly 2 — the ending for the FIRST option, then for the SECOND option; each '
            f'{_part_rule(words, lines, shape.shots_for(1))} Each {ending}.')


def continuation(shape: StoryShape, part: int, remaining_words: int) -> str:
    """The STRUCTURE block for a wish heard in the middle of a part: continue it from the last sentence told."""
    words = max(40, min(shape.words_per_chapter, remaining_words or shape.words_per_chapter))
    lines = (3, max(4, round(words / 13)))
    first = ("CONTINUES the part being told from exactly where TOLD SO FAR stops (never repeat or sum up what was "
             "told; start with the very next moment). The wish visibly happens in its first one or two lines, in a way "
             f"the listener will notice. About {words} words in {lines[0]}-{lines[1]} lines. \"shots\": exactly 1 — "
             "the line where the wish first appears (\"line\", \"description\", \"characters\").")
    if part == 0 and shape.choice_after:
        return (f'"parts": exactly 3.\n- parts[0] — {first} It ends with the narrator asking the listener what should '
                'happen next, naming both options in one or two simple sentences; put that question in "question" and '
                'the two options in parts[0].choices.\n'
                f'- parts[1] — the ending if the listener picks the FIRST option: '
                f'{_part_rule(shape.words_per_chapter, shape.lines_per_chapter, shape.shots_for(1))} It {ENDING}.\n'
                '- parts[2] — the ending if the listener picks the SECOND option: same rules.')
    return (f'"parts": exactly 1 — {first} Then it carries the story on to its warm ending ("And ever since then…"). '
            '"choices": [].')


def _system(request: StoryRequest, shape: StoryShape) -> str:
    hero_rule = f'— it MUST be "{request.hero_name}" (the listener chose this name)' if request.hero_name else ""
    return STORY_SYSTEM.format(reading_level=READING_LEVEL[request.audience], opening_words=shape.opening_words,
                               hero_rule=hero_rule, audience_rules=AUDIENCE_RULES[request.audience],
                               style_example=STYLE_EXAMPLE[request.audience])


def _rename(draft: StoryDraft, hero_name: str | None) -> StoryDraft:
    """Personalisation: the listener's chosen hero name always wins over the model's."""
    if not hero_name or not draft.hero_name.strip():
        return draft
    old = draft.hero_name.split()[0]
    if old.lower() != hero_name.split()[0].lower():
        for field in ("opening", "opening_shot", "logline", "title"):
            setattr(draft, field, getattr(draft, field).replace(old, hero_name))
        for part in draft.parts:
            for line in part.lines:
                line.text = line.text.replace(old, hero_name)
            for shot in part.shots:
                shot.description = shot.description.replace(old, hero_name)
    draft.hero_name = hero_name
    return draft


def _script(part: DraftPart) -> ChapterScript:
    return ChapterScript.model_validate(part.model_dump(include=set(ChapterScript.model_fields)))


def _plan(part: DraftPart, index: int, shape: StoryShape, choice: ChoiceSeed | None = None) -> ChapterPlan:
    slot = shape.slots[min(index, len(shape.slots) - 1)]
    return ChapterPlan(title=part.title, beat=slot.beat, act=slot.act, summary=part.summary, tension=part.tension,
                       ambience=part.ambience, music=part.music, choice=choice)


def assemble(draft: StoryDraft, request: StoryRequest, shape: StoryShape
             ) -> tuple[StoryBible, list[ChapterScript], dict[str, ChapterScript]]:
    """Turn the draft into a bible, the main path's scripts and one ending per choice keyword. Never fails on a
    near-miss: a missing ending turns the story into one without a choice instead of breaking it."""
    draft = _rename(draft, request.hero_name)
    hero = next((c for c in draft.characters if c.name.split()[0].lower() == draft.hero_name.split()[0].lower()),
                draft.characters[0])
    hero.name, hero.look = draft.hero_name, draft.hero_look or hero.look
    hero.id = slugify(hero.name).split("_")[0] or hero.id
    characters = [hero, *[c for c in draft.characters if c is not hero]]
    main, endings = draft.parts[0], list(draft.parts[1:3])
    with_choice = bool(shape.choice_after) and bool(endings)
    if with_choice and len(main.choices) < 2:  # options missing: take them from the question, or the endings
        main.choices = choices_for(draft.question, endings)
    if with_choice and len(endings) == 1:
        endings.append(endings[0])  # one ending for both paths: the story still flows
    labels = [c.label for c in main.choices[:2]]
    asked = draft.question.strip() or (
        f"What should {draft.hero_name} do: {labels[0][:1].lower() + labels[0][1:]}, "
        f"or {labels[1][:1].lower() + labels[1][1:]}?" if len(labels) == 2 else "What should happen next?")
    seed = ChoiceSeed(question=asked, options=labels) if with_choice else None
    chapters = [_plan(main, 0, shape, seed)]
    if with_choice:
        last = _plan(endings[0], 1, shape)
        last.summary = "Whichever way the listener chose: " + " / ".join(e.summary for e in endings[:2])
        chapters.append(last)
    plan = StoryPlan(genre="story", tone=request.audience, theme=draft.theme or draft.logline,
                     characters=characters, chapters=chapters)
    bible = StoryBible.assemble(draft, plan)
    story_shape = shape if with_choice or not shape.choice_after else _without_choice(shape)
    scripts = [finalise_script(_script(main), bible, 0, story_shape)]
    if shape.choice_after and not with_choice:  # no endings came back: never leave a question hanging
        while len(scripts[0].lines) > 3 and "?" in scripts[0].lines[-1].text:
            scripts[0].lines.pop()
    branches = {}
    if with_choice:
        first = scripts[0]
        asked = ask_aloud(first, bible.hero_name, seed.question if seed else "")  # out loud, naming both options
        if bible.chapters[0].choice and asked:
            bible.chapters[0].choice.question = asked
        for option, ending in zip(first.choices[:2], match_endings(first.choices[:2], endings[:2]), strict=False):
            branches[option.keyword] = finalise_script(_script(ending), bible, 1, story_shape)
    return bible, scripts, branches


_MODAL = re.compile(r"^(?:\w+\s+)?(?:should|shall|will|would|could|can|does|do|must)\s+\S+\s+", re.IGNORECASE)


def options_in(question: str) -> list[str]:
    """The two options a spoken question names: "Should Pip follow the light, or wake up Mo?" → ["Follow the light",
    "Wake up Mo"]. Empty if the question does not plainly name two."""
    asked = question.strip().rstrip("?!. ").strip()
    if " or " not in asked:
        return []
    first, second = asked.rsplit(" or ", 1)
    first = re.split(r"[:—]\s*", first.rstrip(", "))[-1]
    labels = [_MODAL.sub("", part).strip(" ,") for part in (first, second)]
    if not all(labels) or any(len(label.split()) > 9 for label in labels):
        return []
    return [label[0].upper() + label[1:] for label in labels]


def choices_for(question: str, endings: list[DraftPart]) -> list[ChoiceOption]:
    """Options for a part whose writer forgot them: the ones the narrator's question names (so the cards always match
    what was asked), or else the endings' titles."""
    labels = options_in(question) or [ending.title for ending in endings[:2]]
    taken: set[str] = set()
    options = []
    for label in labels:
        keyword = keyword_for(label, taken)
        taken.add(keyword)
        options.append(ChoiceOption(keyword=keyword, label=label))
    return options


def _names(question: str, option: ChoiceOption) -> bool:
    heard = set(re.findall(r"[a-z']+", question.lower()))
    wanted = {w for w in re.findall(r"[a-z']+", option.label.lower()) if len(w) > 3 and w not in STOP_WORDS}
    return option.keyword in heard or (bool(wanted) and len(wanted & heard) * 2 >= len(wanted))


def ask_aloud(script: ChapterScript, hero: str, question: str = "") -> str:
    """Make the part end with the narrator asking the question that names both options, out loud. Models sometimes
    write options that differ from the question they wrote; the endings follow the options, so then the question is
    rebuilt from them — what the listener hears, the cards and the endings always agree. Returns the question."""
    options = script.choices[:2]
    asked = [line.text for line in script.lines[-2:] if "?" in line.text]
    spoken = " ".join(asked)
    if len(options) < 2 or (spoken and all(_names(spoken, o) for o in options)):
        if not spoken:
            script.lines.append(ScriptLine(text=question or "What should happen next?", delivery="warm"))
        return question if question and all(_names(question, o) for o in options) else (spoken or question)
    while len(script.lines) > 3 and "?" in script.lines[-1].text:
        script.lines.pop()
    first, second = (o.label[:1].lower() + o.label[1:] for o in options)
    rebuilt = f"What should {hero} do: {first}, or {second}?"
    script.lines.append(ScriptLine(text=rebuilt, delivery="warm"))
    return rebuilt


def match_endings(options: list[ChoiceOption], endings: list[DraftPart]) -> list[DraftPart]:
    """Pair each option with the ending that is about it (models do not always keep the order)."""
    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 3}

    def score(option: ChoiceOption, ending: DraftPart) -> int:
        about = words(f"{ending.title} {ending.summary} {' '.join(line.text for line in ending.lines[:3])}")
        return len(words(f"{option.keyword} {option.label}") & about)

    if len(options) == 2 and len(endings) == 2:
        kept = score(options[0], endings[0]) + score(options[1], endings[1])
        swapped = score(options[0], endings[1]) + score(options[1], endings[0])
        if swapped > kept:
            return [endings[1], endings[0]]
    return endings


def _without_choice(shape: StoryShape) -> StoryShape:
    return replace(shape, slots=[replace(shape.slots[0], choice=False)])


@cache
def draft_schema(parts: int) -> type[StoryDraft]:
    """The draft schema with exactly the parts the structure needs: a missing ending fails validation, which makes the
    router ask the same model to repair its answer (or try the next model) — a story never ends on an open question."""
    return create_model(f"StoryDraft{parts}", __base__=StoryDraft,
                        parts=(list[DraftPart], Field(min_length=parts, max_length=parts)))


@cache
def remainder_schema(parts: int) -> type[StoryRemainder]:
    return create_model(f"StoryRemainder{parts}", __base__=StoryRemainder,
                        parts=(list[DraftPart], Field(min_length=parts, max_length=parts)))


def parts_needed(shape: StoryShape, start: int = 0, chosen: str = "") -> int:
    if not shape.choice_after:
        return 1
    return 3 if start == 0 else 1 if chosen else 2


async def write_story(deps: Deps, request: StoryRequest, prompt: str, shape: StoryShape, notes: str = ""
                      ) -> tuple[StoryBible, list[ChapterScript], dict[str, ChapterScript]]:
    user = STORY_USER.format(prompt=prompt, audience=request.audience, minutes=request.minutes,
                             structure=structure(shape), notes=f"\nFIX THESE PROBLEMS OF A FIRST DRAFT: {notes}"
                             if notes else "")
    draft, _ = await deps.router.structured("storyteller", draft_schema(parts_needed(shape)),
                                            [("system", _system(request, shape)), ("human", user)],
                                            temperature=0.85, observer=deps)
    return assemble(draft, request, shape)


async def revise_story(deps: Deps, request: StoryRequest, shape: StoryShape, bible: StoryBible, told: str,
                       wish: str, part: int, chosen: str = "", fresh: bool = True, remaining_words: int = 0
                       ) -> tuple[list[tuple[int, ChapterScript]], str, list[NewCharacter]]:
    """Weave the listener's wish into everything not yet told. ``part`` is the part being told (0: the opening or the
    first part, 1: an ending); ``fresh``: it has not started yet, so it is rewritten whole — otherwise it continues
    from the last sentence told. Returns (part index, script) pairs in playing order, the choice's question and
    the characters the wish brings in."""
    if fresh:
        needed, rules = parts_needed(shape, part, chosen), structure(shape, part, chosen)
    else:
        needed, rules = (3 if part == 0 and shape.choice_after else 1), continuation(shape, part, remaining_words)
    user = REVISE_USER.format(wish=wish, story=f"{bible.outline()}\n\nTOLD SO FAR:\n{told}", structure=rules)
    remainder, _ = await deps.router.structured("storyteller", remainder_schema(needed),
                                                [("system", _system(request, shape)), ("human", user)],
                                                temperature=0.8, observer=deps,
                                                max_tokens=2400 if needed > 1 else 1400)
    last = len(bible.chapters) - 1
    indexes = [min(part + (i if part == 0 else 0), last) for i in range(len(remainder.parts))]
    parts = list(remainder.parts)
    if len(parts) == 3:  # the first part offers the choice: pair each option with the ending about it
        if len(parts[0].choices) < 2:  # never fall back to the old options: the cards must match the new question
            asked = remainder.question or next((ln.text for ln in reversed(parts[0].lines) if "?" in ln.text), "")
            parts[0].choices = choices_for(asked, parts[1:])
        parts[1:] = match_endings(parts[0].choices[:2], parts[1:])
    scripts: list[tuple[int, ChapterScript]] = []
    for index, draft in zip(indexes, parts, strict=True):
        wish_shot = draft.shots[0].model_copy() if draft.shots else None
        script = finalise_script(_script(draft), bible, index, shape)
        if not fresh and not scripts and wish_shot and not script.shots:  # the moment the wish comes true
            known = {c.id for c in bible.characters}
            wish_shot.characters = [c for c in (bible.resolve_speaker(c) for c in wish_shot.characters) if c in known]
            wish_shot.line = min(wish_shot.line, len(script.lines) - 1)
            script.shots = [wish_shot]
        scripts.append((index, script))
    question = remainder.question.strip()
    if len(scripts) == 3:  # the narrator must ask, out loud, naming both options
        question = ask_aloud(scripts[0][1], bible.hero_name, question)
    known = {c.name.lower() for c in bible.characters}
    newcomers = [c for c in remainder.new_characters if c.name.lower() not in known]
    return scripts, question, newcomers
