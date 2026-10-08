"""Shared fixtures: settings and a scripted model router — every test runs offline."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from storyweaver.config import Settings
from storyweaver.llm import CallInfo

OPENING = {
    "title": "Pip and the Night Lantern", "logline": "A shy hedgehog learns the dark can be kind.",
    "hero_name": "Pip", "hero_look": "a small brown hedgehog with a red scarf",
    "setting": "A meadow by an old oak tree.", "opening": "Once upon a time, in a meadow, lived a hedgehog named Pip.",
    "opening_shot": "Pip under the oak at sunset.", "art_style": "soft watercolour",
    "narrator": {"gender": "female", "accent": "british", "style": "warm"},
    "opening_music": "wonder", "opening_ambience": ["forest"],
}
PLAN = {
    "genre": "fable", "tone": "cosy", "theme": "courage",
    "hero_arc": {"want": "to sleep outside", "flaw": "afraid of the dark", "growth": "finds the stars"},
    "seeds": [{"setup": "a lantern", "payoff": "lights the way"}],
    "characters": [{"id": "pip", "name": "Pip", "role": "hero", "look": "brown hedgehog", "gender": "male",
                    "age": "child"},
                   {"id": "mo", "name": "Mo", "role": "friend", "look": "a pink-nosed mole", "gender": "male"}],
    "chapters": [
        {"title": "The Glow", "summary": "Pip sees a glow.", "tension": 0.4, "ambience": ["night"], "music": "mystery",
         "choice": {"question": "Follow it or wake Mo?", "options": ["Follow the glow", "Wake up Mo"]}},
        {"title": "Home", "summary": "Whichever way, Pip finds the stars.", "tension": 0.3, "music": "joy"},
    ],
}


def chapter(index: int, choice: bool) -> dict[str, Any]:
    walk = "They walked past the old oak tree and the quiet pond, and the soft grass tickled their feet."
    lines = [{"speaker": "narrator", "text": "The moon rose over the meadow. " + walk, "delivery": "warm"},
             {"speaker": "Pip", "text": "Is that a light? It looks like a tiny star that fell down.",
              "delivery": "whisper"},
             {"speaker": "mo", "text": "Let us go and see. I will hold your paw all the way.", "delivery": "playful"},
             {"speaker": "narrator", "text": walk, "delivery": "warm"},
             {"speaker": "Pip", "text": "I am a little bit scared, but I am brave too.", "delivery": "calm"},
             {"speaker": "narrator", "text": walk + " The light grew bigger and warmer.", "delivery": "awe"},
             {"speaker": "mo", "text": "Look, it is a lantern, and it is waiting just for us.", "delivery": "excited"},
             {"speaker": "narrator", "text": "Should Pip follow the glow, or wake up Mo? " + walk, "delivery": "warm"}]
    return {"title": f"Chapter {index}", "lines": lines, "shots": [{"line": 0, "description": "Pip in moonlight"}],
            "choices": [{"keyword": "glow", "label": "Follow the glow"}, {"keyword": "mo", "label": "Wake up Mo"}]
            if choice else [], "summary": f"Chapter {index} happened.", "facts": []}


def part(title: str, choice: bool, mention: str = "") -> dict[str, Any]:
    body = chapter(1, choice)
    if mention:
        body["lines"][0]["text"] = f"{mention} {body['lines'][0]['text']}"
    return {**body, "title": title, "summary": f"{title}. {mention}", "music": "joy", "ambience": ["forest"],
            "tension": 0.4}


# The whole story, as the Storyteller returns it — the endings deliberately in the opposite order to the options.
DRAFT = {**OPENING, "theme": "courage", "question": "Should Pip follow the glow, or wake up Mo?",
         "characters": PLAN["characters"],
         "parts": [part("The Glow", True), part("Mo Wakes Up", False, "Pip woke up Mo, his friend."),
                   part("Following the Glow", False, "Pip followed the glow across the meadow.")]}


def default_script() -> dict[str, Any]:
    def writer(messages: list) -> dict[str, Any]:
        index = int(re.search(r"THIS CHAPTER: (\d+) of", messages[-1][1]).group(1))
        return chapter(index, choice=index == 1)

    return {
        "guardian": {"decision": "allow", "category": "none", "reason": "fine", "safe_request": "", "alternatives": []},
        "storyteller": DRAFT, "writer": writer,
        "editor": {"approved": True, "safety_ok": True, "issues": [], "notes": ""},
        "interpreter": {"kind": "unclear"},
    }


class ScriptedRouter:
    """Stands in for LLMRouter: scripted outputs per role; records every call (role, messages)."""

    def __init__(self, settings: Settings, script: dict[str, Any] | None = None):
        self.settings = settings
        self.script = {**default_script(), **(script or {})}
        self.calls: list[tuple[str, list]] = []

    def chain(self, role: str) -> list[tuple[str, str]]:
        return []  # the Lore Scout has no tool-calling model here, so it skips research

    async def structured(self, role: str, schema: type, messages: list, **kwargs: Any):
        self.calls.append((role, list(messages)))
        value = self.script[role]
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(messages)
        info = CallInfo(role, "fake", "fake-model", 1)
        if kwargs.get("observer"):
            kwargs["observer"].trace(info)
        return schema.model_validate(value), info

    def roles(self) -> list[str]:
        return [role for role, _ in self.calls]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(groq_api_key="test-groq", gemini_api_key="", cloudflare_api_token="", cloudflare_account_id="",
                    pollinations_key="", models_dir=tmp_path / "models", _env_file=None)


@pytest.fixture
def router(settings: Settings) -> ScriptedRouter:
    return ScriptedRouter(settings)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_network(*args: Any, **kwargs: Any) -> float:
        return 0.01

    from storyweaver.safety import guardian
    monkeypatch.setattr(guardian, "injection_score", no_network)
