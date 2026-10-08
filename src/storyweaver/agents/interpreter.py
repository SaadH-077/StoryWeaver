"""Interpreter ("the listener's ear"): understands what the listener says while the story plays.

Fast paths first, in code and instant: a tapped option, or speech containing an option's keyword ("the tunnels!")
or an ordinal ("the second one"), is a choice; a sentence that plainly asks for something ("please add a friendly
owl", "make the dragon sing") is a wish, passed on word for word. Only questions and ambiguous input ("can the owl
tell a joke?", "what colour is the lantern?") go to the language model. Everything is screened by the safety lexicon
first.
"""

from __future__ import annotations

import re

from ..llm import LLMError
from ..prompts import INTERPRETER_SYSTEM, INTERPRETER_USER
from ..safety.guardian import screen_snippet
from ..schemas import ChoiceOption, ListenerIntent
from .deps import Deps
from .writer import story_so_far

ORDINALS = {
    0: ("first", "1", "option one", "number one", "the former"),
    1: ("second", "2", "option two", "number two", "the latter"),
    2: ("third", "3", "option three", "number three"),
}


WISH = re.compile(r"^(?:(?:please|now|and|oh|ooh|okay|ok)[\s,!]+)*"
                  r"(?:i (?:want|wish|would like)\b|(?:(?:can|could|would) you\s+|let'?s\s+)?"
                  r"(?:add|make|give|bring|put|turn|change|send|include|introduce|let|have)\b)", re.IGNORECASE)


def as_wish(text: str) -> str | None:
    """The wish itself, if the sentence plainly asks for something to happen in the story (no model needed)."""
    clean = text.strip()
    if not clean or clean.endswith("?") or not WISH.match(clean):
        return None
    clean = re.sub(r"^(?:(?:please|now|and|oh|ooh|okay|ok)[\s,!]+)+", "", clean, flags=re.IGNORECASE).rstrip(".! ")
    return clean[:1].upper() + clean[1:]


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ÿ]+", text.lower()) if len(w) > 3}


def match_choice(text: str, choices: list[ChoiceOption]) -> str | None:
    """Resolve a choice without an LLM when the words make it unambiguous."""
    if not choices or not text:
        return None
    lowered = text.lower()
    words = set(re.findall(r"[a-zà-ÿ0-9']+", lowered))
    hits = {c.keyword for c in choices if c.keyword in words or f"{c.keyword}s" in words}
    if len(hits) == 1:
        return hits.pop()
    if hits:  # several keywords mentioned -> ambiguous
        return None
    matched = []
    for choice in choices:
        own = _content_words(choice.label)
        others = set().union(*(_content_words(o.label) for o in choices if o is not choice))
        if words & (own - others):
            matched.append(choice.keyword)
    if len(matched) == 1:
        return matched[0]
    for idx, choice in enumerate(choices):
        if any(re.search(rf"\b{re.escape(o)}\b", lowered) for o in ORDINALS.get(idx, ())):
            return choice.keyword
    return None


async def interpret(deps: Deps, text: str, choices: list[ChoiceOption], summaries: list[str],
                    audience: str) -> ListenerIntent:
    ok, _ = screen_snippet(text)
    if not ok:
        return ListenerIntent(kind="unclear")
    keyword = match_choice(text, choices)
    if keyword:
        return ListenerIntent(kind="choice", choice_keyword=keyword)
    wish = None if choices else as_wish(text)  # while a choice is open, the model decides what was meant
    if wish:
        return ListenerIntent(kind="steer", steer=wish)
    options = ", ".join(f"{c.keyword} = {c.label}" for c in choices) or "none (story is playing)"
    user = INTERPRETER_USER.format(audience=audience, options=options, story_so_far=story_so_far(summaries),
                                   text=text)
    try:
        intent, _ = await deps.router.structured(
            "interpreter", ListenerIntent, [("system", INTERPRETER_SYSTEM), ("human", user)],
            temperature=0.2, observer=deps)
    except LLMError:
        return ListenerIntent(kind="steer", steer=text) if not choices else ListenerIntent(kind="unclear")
    valid = {c.keyword for c in choices}
    if intent.kind == "choice" and intent.choice_keyword not in valid:
        intent = ListenerIntent(kind="steer", steer=text) if choices else ListenerIntent(kind="unclear")
    for field in ("steer", "answer"):  # the model's own words are screened too
        value = getattr(intent, field)
        if value and not screen_snippet(value)[0]:
            return ListenerIntent(kind="unclear")
    return intent
