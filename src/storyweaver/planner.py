"""Duration planning: turn "I have 2 minutes" into a story shape.

The listener picks a length in minutes; this module decides how many chapters, words and pictures fit, and which
beat of the story each chapter carries. Every story — even a one-minute tale — has a moment where the listener decides
what happens next. The beats combine three classic structures:

* the **Story Spine** (Kenn Adams): Once upon a time… Every day… But one day… Because of that… Until finally…
  And ever since then… — it forces cause and effect, which is what makes a story easy to follow;
* **Freytag's pyramid** for rising tension, climax and resolution;
* **Propp's functions** (chosen per chapter by the Story Architect) for the concrete events.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Natural narration speed of the neural voices we use (words per minute), measured on our own stories.
WORDS_PER_MINUTE = 150


@dataclass(frozen=True)
class ChapterSlot:
    beat: str
    act: str
    tension: float
    choice: bool = False
    shots: int = 0  # pictures painted for this chapter (the opening always has one)


@dataclass(frozen=True)
class StoryShape:
    minutes: int
    opening_words: int
    words_per_chapter: int
    lines_per_chapter: tuple[int, int]
    slots: list[ChapterSlot] = field(default_factory=list)

    @property
    def chapters(self) -> int:
        return len(self.slots)

    @property
    def choice_after(self) -> list[int]:
        """1-based numbers of the chapters that end with a listener choice."""
        return [i for i, slot in enumerate(self.slots, start=1) if slot.choice]

    @property
    def pictures(self) -> int:
        """Pictures in the whole story: the opening's plus each chapter's — one per minute, a fixed budget."""
        return 1 + sum(slot.shots for slot in self.slots)

    def shots_for(self, index: int) -> int:
        return self.slots[index].shots if 0 <= index < len(self.slots) else 0

    @property
    def total_words(self) -> int:
        return self.opening_words + self.words_per_chapter * self.chapters

    def describe(self) -> str:
        return (f"{self.chapters} chapter(s) after the opening, ~{self.words_per_chapter} words each, "
                f"{len(self.choice_after)} listener choice(s), {self.pictures} pictures in all")


# minutes -> chapters as (beat, Freytag act, tension, choice at the end, pictures in the chapter)
_SHAPES: dict[int, tuple[int, int, list[tuple[str, str, float, bool, int]]]] = {
    # (opening words, words per chapter, chapters). Story time ≈ words / 150 per minute; targets sit a little
    # above the exact duration because writers reliably undershoot (measured in the evaluation).
    1: (40, 62, [("But one day… / Because of that…", "rising_action", 0.45, True, 0),
                 ("Until finally… / And ever since then…", "resolution", 0.55, False, 0)]),
    2: (60, 155, [("But one day… / Because of that…", "rising_action", 0.45, True, 0),
                  ("Until finally… / And ever since then…", "resolution", 0.6, False, 1)]),
    3: (75, 240, [("But one day… / Because of that…", "rising_action", 0.45, True, 1),
                  ("Until finally… / And ever since then…", "resolution", 0.7, False, 1)]),
}
LENGTHS = tuple(_SHAPES)


def shape_for(minutes: int, audience: str = "family") -> StoryShape:
    opening, per_chapter, beats = _SHAPES.get(minutes, _SHAPES[2])
    if audience == "kids":  # little ones: same time, slower and simpler — a few words fewer per chapter
        per_chapter = int(per_chapter * 0.92)
    words_per_line = 12 if audience == "kids" else 14
    lines = max(4, per_chapter // words_per_line)
    slots = [ChapterSlot(*beat) for beat in beats]
    return StoryShape(minutes, opening, per_chapter, (lines, lines + 4), slots)


def estimate_seconds(words: int) -> float:
    return words / WORDS_PER_MINUTE * 60
