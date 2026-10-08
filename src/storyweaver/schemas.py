"""Domain models shared by the agents, the API and the evaluation.

LLM outputs are validated against these models. Validators are deliberately *lenient*: language models
occasionally invent an enum value ("sfx": "rain") or vary capitalisation ("Pip" vs "pip"). Rather than failing a
whole chapter, unknown values are mapped to the closest supported one or to a safe default.

Note: LLM-facing schemas avoid string-length limits and large array limits in the JSON schema itself (some
providers reject them); bounds are enforced by validators instead.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ------------------------------------------------------------------------------------------------------
# Controlled vocabularies (shared with the browser's procedural sound engine — keep in sync with public/js)
# ------------------------------------------------------------------------------------------------------
AMBIENCE = ("rain", "storm", "wind", "ocean", "river", "fire", "night", "forest",
            "city", "machine", "space", "cave", "underwater", "magic")
SFX = ("thunder", "chime", "whoosh", "heartbeat", "footsteps", "knock",
       "bell", "sparkle", "beep", "splash", "tick", "gust")
DELIVERY = ("neutral", "warm", "calm", "excited", "playful", "whisper", "tense", "scared", "sad", "awe")
MUSIC_MOODS = ("wonder", "adventure", "mystery", "tension", "calm", "joy", "melancholy", "triumph")
ACTS = ("exposition", "rising_action", "climax", "falling_action", "resolution")

# Propp's narrative functions (Morphology of the Folktale), as used in the Kahaani system.
PROPP_FUNCTIONS = (
    "absentation", "interdiction", "violation", "reconnaissance", "delivery", "trickery", "complicity",
    "villainy_or_lack", "mediation", "counteraction", "departure", "donor_test", "hero_reaction",
    "magical_agent", "guidance", "struggle", "branding", "victory", "liquidation", "return", "pursuit",
    "rescue", "unrecognised_arrival", "unfounded_claims", "difficult_task", "solution", "recognition",
    "exposure", "transfiguration", "punishment", "celebration",
)

Ambience = Literal[AMBIENCE]  # type: ignore[valid-type]
Sfx = Literal[SFX]  # type: ignore[valid-type]
Delivery = Literal[DELIVERY]  # type: ignore[valid-type]
MusicMood = Literal[MUSIC_MOODS]  # type: ignore[valid-type]
Act = Literal[ACTS]  # type: ignore[valid-type]
Audience = Literal["kids", "family", "adults"]

_SYNONYMS: dict[str, str] = {
    # ambience
    "rainfall": "rain", "drizzle": "rain", "thunderstorm": "storm", "tempest": "storm", "breeze": "wind",
    "sea": "ocean", "waves": "ocean", "beach": "ocean", "stream": "river", "water": "river", "brook": "river",
    "campfire": "fire", "fireplace": "fire", "crickets": "night", "evening": "night", "woods": "forest",
    "jungle": "forest", "birds": "forest", "traffic": "city", "street": "city", "urban": "city",
    "crowd": "city", "market": "city", "engine": "machine", "factory": "machine", "spaceship": "machine",
    "robot": "machine", "stars": "space", "cosmos": "space", "tunnel": "cave", "dungeon": "cave",
    "lake": "river", "sparkles": "magic", "shimmer": "magic", "mystical": "magic", "snow": "wind",
    "desert": "wind", "garden": "forest", "meadow": "forest", "castle": "wind", "village": "forest",
    # sfx
    "rumble": "thunder", "lightning": "thunder", "ding": "chime", "chimes": "chime", "swoosh": "whoosh",
    "swish": "whoosh", "heart": "heartbeat", "steps": "footsteps", "footstep": "footsteps",
    "door": "knock", "door_knock": "knock", "knocking": "knock", "glimmer": "sparkle", "twinkle": "sparkle",
    "magic_sparkle": "sparkle", "blip": "beep", "robot_beep": "beep", "water_splash": "splash",
    "clock": "tick", "ticking": "tick", "wind_gust": "gust",
    # delivery
    "whispering": "whisper", "whispered": "whisper", "softly": "whisper", "happy": "playful",
    "cheerful": "playful", "joyful": "excited", "eager": "excited", "urgent": "tense", "worried": "tense",
    "nervous": "scared", "afraid": "scared", "fearful": "scared", "frightened": "scared",
    "gentle": "warm", "kind": "warm", "soothing": "calm", "serious": "calm", "amazed": "awe",
    "wonder": "awe", "mysterious": "whisper", "sorrowful": "sad", "melancholy": "sad", "proud": "warm",
    "curious": "playful", "surprised": "excited", "angry": "tense",
    # music
    "magical": "wonder", "epic": "adventure", "exciting": "adventure", "suspense": "tension",
    "danger": "tension", "peaceful": "calm", "happy_music": "joy", "sad_music": "melancholy",
    "victory": "triumph", "heroic": "triumph", "spooky": "mystery", "cozy": "calm", "cosy": "calm",
    "playful_music": "joy", "hopeful": "wonder",
    # acts
    "rising": "rising_action", "falling": "falling_action", "intro": "exposition",
    "introduction": "exposition", "ending": "resolution", "conclusion": "resolution",
}


def _norm(value: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


def coerce_vocab(value: Any, allowed: tuple[str, ...], default: str | None) -> str | None:
    """Map a free-form LLM value onto a controlled vocabulary, falling back to ``default``."""
    if value is None:
        return default
    key = _norm(value)
    if key in allowed:
        return key
    mapped = _SYNONYMS.get(key)
    if mapped in allowed:
        return mapped
    for word in key.split("_"):  # e.g. "soft_rain" -> "rain"
        if word in allowed:
            return word
        if _SYNONYMS.get(word) in allowed:
            return _SYNONYMS[word]
    return default


def slugify(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return slug or "narrator"


def _emoji(value: Any) -> str:
    """Keep only pictographic characters (and their joiners), at most one short emoji sequence."""
    text = "".join(ch for ch in str(value or "") if ord(ch) >= 0x2000 or ch == "\u200d")
    return text[:8]


def _strings(value: Any, limit: int) -> list[str]:
    return [str(v) for v in (value or []) if str(v).strip()][:limit]


# ------------------------------------------------------------------------------------------------------
# Request
# ------------------------------------------------------------------------------------------------------
class StoryRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=300)
    audience: Audience = "family"
    minutes: Literal[1, 2, 3] = 2
    hero_name: str | None = Field(default=None, max_length=24)

    @field_validator("prompt")
    @classmethod
    def _strip_prompt(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("hero_name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' \-]", "", value).strip()
        return " ".join(part.capitalize() for part in cleaned.split()) or None


# ------------------------------------------------------------------------------------------------------
# Safety
# ------------------------------------------------------------------------------------------------------
class GuardianVerdict(BaseModel):
    decision: Literal["allow", "soften", "refuse"] = "allow"
    category: str = "none"
    reason: str = ""
    safe_request: str = ""
    alternatives: list[str] = Field(default_factory=list)

    @field_validator("decision", mode="before")
    @classmethod
    def _decision(cls, value: Any) -> str:
        key = _norm(value)
        if key in ("allow", "soften", "refuse"):
            return key
        if key in ("block", "deny", "reject", "unsafe", "violation"):
            return "refuse"
        if key in ("modify", "rewrite", "adjust"):
            return "soften"
        return "allow"

    @field_validator("alternatives", mode="before")
    @classmethod
    def _alts(cls, value: Any) -> list[str]:
        return _strings(value, 3)


# ------------------------------------------------------------------------------------------------------
# Lore (research)
# ------------------------------------------------------------------------------------------------------
class LoreFact(BaseModel):
    subject: str
    fact: str
    source: str = ""


class LoreNotes(BaseModel):
    facts: list[str] = Field(default_factory=list)

    @field_validator("facts", mode="before")
    @classmethod
    def _cap(cls, value: Any) -> list[str]:
        return _strings(value, 4)


# ------------------------------------------------------------------------------------------------------
# Story bible (Story Architect)
# ------------------------------------------------------------------------------------------------------
class NarratorSpec(BaseModel):
    gender: Literal["female", "male"] = "female"
    accent: Literal["american", "british"] = "british"
    style: str = "warm, gentle storyteller"

    @field_validator("gender", mode="before")
    @classmethod
    def _gender(cls, value: Any) -> str:
        return "male" if _norm(value) in ("male", "man", "m") else "female"

    @field_validator("accent", mode="before")
    @classmethod
    def _accent(cls, value: Any) -> str:
        return "american" if "americ" in _norm(value) or _norm(value) == "us" else "british"


class CharacterSpec(BaseModel):
    id: str
    name: str
    role: str = "friend"
    description: str = ""
    look: str = ""
    gender: Literal["female", "male", "neutral"] = "neutral"
    age: Literal["child", "teen", "adult", "elder"] = "adult"
    accent: Literal["american", "british"] = "american"
    emoji: str = ""  # one emoji that shows who they are (the cast panel while the story plays)

    @field_validator("emoji", mode="before")
    @classmethod
    def _emoji(cls, value: Any) -> str:
        return _emoji(value)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data["id"] = slugify(data.get("id") or data.get("name") or "character")
            data.setdefault("name", data["id"].replace("_", " ").title())
            gender = _norm(data.get("gender", "neutral"))
            data["gender"] = ("female" if gender in ("female", "woman", "girl", "f")
                              else "male" if gender in ("male", "man", "boy", "m") else "neutral")
            age = _norm(data.get("age", "adult"))
            data["age"] = age if age in ("child", "teen", "adult", "elder") else (
                "child" if age in ("kid", "young_child", "baby", "little") else
                "elder" if age in ("old", "elderly", "senior", "ancient") else
                "teen" if age in ("teenager", "young", "youth") else "adult")
            data["accent"] = "british" if "brit" in _norm(data.get("accent", "")) else "american"
        return data


class ChoiceSeed(BaseModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=3)


class HeroArc(BaseModel):
    want: str = ""
    flaw: str = ""
    growth: str = ""


class Seed(BaseModel):
    """A setup planted early that must pay off later (keeps the story coherent and satisfying)."""
    setup: str
    payoff: str = ""


class ChapterPlan(BaseModel):
    title: str
    beat: str = ""
    act: Act = "rising_action"
    propp: list[str] = Field(default_factory=list)
    summary: str
    tension: float = 0.5
    ambience: list[Ambience] = Field(default_factory=lambda: ["wind"])
    music: MusicMood = "wonder"
    choice: ChoiceSeed | None = None

    @field_validator("act", mode="before")
    @classmethod
    def _act(cls, value: Any) -> str:
        return coerce_vocab(value, ACTS, "rising_action")  # type: ignore[return-value]

    @field_validator("tension", mode="before")
    @classmethod
    def _tension(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        if number > 1:  # models sometimes answer on a 1-10 scale
            number /= 10
        return min(max(number, 0.0), 1.0)

    @field_validator("ambience", mode="before")
    @classmethod
    def _ambience(cls, value: Any) -> list[str]:
        items = value if isinstance(value, list) else [value]
        coerced = [coerce_vocab(v, AMBIENCE, None) for v in items]
        unique = list(dict.fromkeys(v for v in coerced if v))
        return unique[:2] or ["wind"]

    @field_validator("music", mode="before")
    @classmethod
    def _music(cls, value: Any) -> str:
        return coerce_vocab(value, MUSIC_MOODS, "wonder")  # type: ignore[return-value]

    @field_validator("propp", mode="before")
    @classmethod
    def _propp(cls, value: Any) -> list[str]:
        return [_norm(v) for v in (value or [])][:3]

    @field_validator("choice", mode="before")
    @classmethod
    def _choice(cls, value: Any) -> Any:
        if not value or (isinstance(value, dict) and len(value.get("options") or []) < 2):
            return None
        return value


class StoryOpening(BaseModel):
    """What the Storyteller writes first — small enough to arrive in about a second, so narration can begin
    while the Story Architect designs the rest. Everything here is heard or seen first and never changes."""

    # Creative fields are required on purpose: models tend to skip optional fields, and a missing art style or
    # opening makes the whole story blander. A missing field triggers one repair round in the router.
    title: str
    logline: str
    hero_name: str
    hero_look: str
    setting: str
    opening: str
    opening_shot: str
    art_style: str
    narrator: NarratorSpec = Field(default_factory=NarratorSpec)
    opening_music: MusicMood = "wonder"
    opening_ambience: list[Ambience] = Field(default_factory=lambda: ["wind"])

    @field_validator("opening_music", mode="before")
    @classmethod
    def _opening_music(cls, value: Any) -> str:
        return coerce_vocab(value, MUSIC_MOODS, "wonder")  # type: ignore[return-value]

    @field_validator("opening_ambience", mode="before")
    @classmethod
    def _opening_ambience(cls, value: Any) -> list[str]:
        items = value if isinstance(value, list) else [value]
        coerced = [coerce_vocab(v, AMBIENCE, None) for v in items]
        return list(dict.fromkeys(v for v in coerced if v))[:2] or ["wind"]


class StoryPlan(BaseModel):
    """What the Story Architect designs around an opening the listener is already hearing."""

    genre: str
    tone: str
    theme: str
    hero_arc: HeroArc = Field(default_factory=HeroArc)
    seeds: list[Seed] = Field(default_factory=list)
    characters: list[CharacterSpec] = Field(min_length=1, max_length=5)
    chapters: list[ChapterPlan] = Field(min_length=1, max_length=7)

    @field_validator("seeds", mode="before")
    @classmethod
    def _seeds(cls, value: Any) -> list[Any]:
        out = []
        for item in (value or [])[:3]:
            out.append({"setup": item, "payoff": ""} if isinstance(item, str) else item)
        return out


class StoryBible(StoryOpening, StoryPlan):
    """The whole design every chapter must agree on: the opening plus the plan (assembled in code)."""

    @classmethod
    def assemble(cls, opening: StoryOpening, plan: StoryPlan) -> StoryBible:
        return cls.model_validate({**plan.model_dump(), **opening.model_dump()})

    def character(self, speaker_id: str) -> CharacterSpec | None:
        return next((c for c in self.characters if c.id == speaker_id), None)

    def resolve_speaker(self, raw: str) -> str:
        """Map whatever the writer used ("Pip", "PIP", "pip_the_hedgehog") onto a known speaker id."""
        slug = slugify(raw)
        if slug in ("narrator", "narration", "storyteller", "voice_over"):
            return "narrator"
        for c in self.characters:
            if slug in (c.id, slugify(c.name)) or slug.startswith(c.id) or c.id.startswith(slug):
                return c.id
        first_names = {slugify(c.name).split("_")[0]: c.id for c in self.characters}
        return first_names.get(slug.split("_")[0], slug)

    def outline(self) -> str:
        chars = "\n".join(f"- {c.id}: {c.name}, {c.role}, {c.age} {c.gender}. {c.description} Looks: {c.look}"
                          for c in self.characters)
        seeds = "; ".join(f"{s.setup} -> {s.payoff}" for s in self.seeds) or "-"
        return (f"Title: {self.title}\nLogline: {self.logline}\nGenre/tone: {self.genre}, {self.tone}\n"
                f"Hero: {self.hero_name} ({self.hero_look})\n"
                f"Theme: {self.theme}\nSetting: {self.setting}\n"
                f"Hero arc: wants {self.hero_arc.want or '-'}; flaw/fear {self.hero_arc.flaw or '-'}; "
                f"grows by {self.hero_arc.growth or '-'}\nSetups to pay off: {seeds}\n"
                f"Opening (already told to the listener): {self.opening}\nCharacters:\n{chars}")


# ------------------------------------------------------------------------------------------------------
# Chapter script (Writer) and review (Editor)
# ------------------------------------------------------------------------------------------------------
class ScriptLine(BaseModel):
    speaker: str = "narrator"
    text: str
    delivery: Delivery = "neutral"
    sfx: Sfx | None = None

    @field_validator("delivery", mode="before")
    @classmethod
    def _delivery(cls, value: Any) -> str:
        return coerce_vocab(value, DELIVERY, "neutral")  # type: ignore[return-value]

    @field_validator("sfx", mode="before")
    @classmethod
    def _sfx(cls, value: Any) -> str | None:
        if value in (None, "", "none", "None", "null"):
            return None
        return coerce_vocab(value, SFX, None)

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", value)  # stray "[whispering]" stage directions
        value = re.sub(r"^\s*\([^)]{1,40}\)\s*", "", value)
        value = re.sub(r"\*+", "", value)  # markdown emphasis would be read out oddly
        value = value.strip()
        # a line wrapped in quotation marks loses them (it is spoken in the character's own voice anyway);
        # quotes inside a narrator line stay balanced
        if len(value) > 1 and value[0] in '"“' and value[-1] in '"”' and not re.search(r'["“”]', value[1:-1]):
            value = value[1:-1].strip()
        return value[:600]


class Shot(BaseModel):
    """A picture-book illustration that appears when narration reaches ``line``."""
    line: int = 0
    description: str
    characters: list[str] = Field(default_factory=list)

    @field_validator("line", mode="before")
    @classmethod
    def _line(cls, value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @field_validator("characters", mode="before")
    @classmethod
    def _chars(cls, value: Any) -> list[str]:
        return [slugify(v) for v in (value or [])][:3]


class ChoiceOption(BaseModel):
    keyword: str
    label: str

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            words = [w for w in re.findall(r"[A-Za-z']+", data) if len(w) > 3]
            return {"keyword": (words[-1] if words else data).lower(), "label": data}
        return data

    @field_validator("keyword")
    @classmethod
    def _one_word(cls, value: str) -> str:
        words = re.findall(r"[A-Za-zÀ-ÿ']+", value.lower())
        return words[0] if words else value.lower()

    @field_validator("label")
    @classmethod
    def _short_label(cls, value: str) -> str:
        words = value.strip().rstrip(".").split()
        return " ".join(words[:8]) + ("…" if len(words) > 8 else "")


class ChapterScript(BaseModel):
    title: str
    # Line-count bounds are enforced by the validator, not the JSON schema (some providers reject large
    # minItems/maxItems on arrays of objects).
    lines: list[ScriptLine]
    shots: list[Shot] = Field(default_factory=list)
    choices: list[ChoiceOption] = Field(default_factory=list, max_length=3)
    summary: str
    facts: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _repair(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data["lines"] = [{"speaker": "narrator", "text": ln} if isinstance(ln, str) else ln
                             for ln in data.get("lines") or []]
            choices = data.get("choices") or []
            data["choices"] = [] if len(choices) == 1 else choices
            shots = data.get("shots") or []
            data["shots"] = [{"description": s} if isinstance(s, str) else s for s in shots][:4]
        return data

    @field_validator("facts", mode="before")
    @classmethod
    def _facts(cls, value: Any) -> list[str]:
        return _strings(value, 6)

    @model_validator(mode="after")
    def _bounds(self) -> ChapterScript:
        self.lines = [line for line in self.lines if line.text][:40]
        if len(self.lines) < 3:
            raise ValueError("a chapter needs at least 3 spoken lines")
        for shot in self.shots:
            shot.line = min(shot.line, len(self.lines) - 1)
        return self

    @property
    def word_count(self) -> int:
        return sum(len(line.text.split()) for line in self.lines)

    def as_text(self) -> str:
        return "\n".join(f"{line.speaker.upper()}: {line.text}" for line in self.lines)


class DraftPart(ChapterScript):
    """One part of a story written in a single pass, with its own music, ambience and tension."""

    music: MusicMood = "wonder"
    ambience: list[Ambience] = Field(default_factory=lambda: ["wind"])
    tension: float = 0.5

    @field_validator("music", mode="before")
    @classmethod
    def _music(cls, value: Any) -> str:
        return coerce_vocab(value, MUSIC_MOODS, "wonder")  # type: ignore[return-value]

    @field_validator("ambience", mode="before")
    @classmethod
    def _ambience(cls, value: Any) -> list[str]:
        items = value if isinstance(value, list) else [value]
        return list(dict.fromkeys(v for v in (coerce_vocab(x, AMBIENCE, None) for x in items) if v))[:2] or ["wind"]

    @field_validator("tension", mode="before")
    @classmethod
    def _tension(cls, value: Any) -> float:
        return ChapterPlan._tension(value)  # type: ignore[call-arg]


class StoryDraft(StoryOpening):
    """The whole story from one model call: opening, cast, and every part — for a story with a choice, the part
    that ends with the question and one ending per option. Written before narration starts, so nothing waits."""

    theme: str = ""
    characters: list[CharacterSpec] = Field(min_length=1, max_length=4)
    question: str = ""
    parts: list[DraftPart] = Field(min_length=1, max_length=3)


class NewCharacter(BaseModel):
    """Someone a listener's wish brings into the story (shown joining the cast)."""

    name: str
    emoji: str = ""
    description: str = ""

    @field_validator("emoji", mode="before")
    @classmethod
    def _emoji(cls, value: Any) -> str:
        return _emoji(value)


class StoryRemainder(BaseModel):
    """The not-yet-told parts, rewritten to include a listener's wish."""

    parts: list[DraftPart] = Field(min_length=1, max_length=3)
    question: str = ""  # the choice's question, when the rewritten part offers the choice
    new_characters: list[NewCharacter] = Field(default_factory=list)

    @field_validator("new_characters", mode="before")
    @classmethod
    def _few(cls, value: Any) -> list[Any]:
        return [v for v in (value or []) if isinstance(v, dict) and v.get("name")][:3]


class EditorReview(BaseModel):
    approved: bool = True
    safety_ok: bool = True
    issues: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("issues", mode="before")
    @classmethod
    def _issues(cls, value: Any) -> list[str]:
        return _strings(value, 6)


# ------------------------------------------------------------------------------------------------------
# Listener input (Interpreter)
# ------------------------------------------------------------------------------------------------------
class ListenerIntent(BaseModel):
    kind: Literal["choice", "steer", "question", "unclear"] = "unclear"
    choice_keyword: str | None = None
    steer: str | None = None
    answer: str | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: Any) -> str:
        key = _norm(value)
        return key if key in ("choice", "steer", "question", "unclear") else "unclear"
