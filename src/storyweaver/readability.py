"""Readability metrics without external dependencies (Flesch Reading Ease, Flesch-Kincaid grade).

Used by the Editor (a chapter that is too hard for its audience is sent back) and by the evaluation, so "simple,
flowing English" is measured rather than hoped for.
"""

from __future__ import annotations

import re

_VOWEL_GROUPS = re.compile(r"[aeiouy]+")
_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*\s+|[.!?]+$")

# Target reading level (US school grade) per audience: max grade before the Editor asks for simpler language.
MAX_GRADE = {"kids": 4.0, "family": 6.5, "adults": 9.5}


def count_syllables(word: str) -> int:
    word = word.lower().strip(".,!?;:\"'()-—…")
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    return max(1, len(_VOWEL_GROUPS.findall(word)))


def _sentences(text: str) -> int:
    return max(1, len([s for s in _SENTENCE_END.split(text) if s and s.strip()]))


def stats(text: str) -> dict[str, float]:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    n_words = max(1, len(words))
    n_sentences = _sentences(text)
    n_syllables = sum(count_syllables(w) for w in words)
    words_per_sentence = n_words / n_sentences
    syllables_per_word = n_syllables / n_words
    grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
    ease = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
    return {"words": float(len(words)), "sentences": float(n_sentences),
            "words_per_sentence": round(words_per_sentence, 1), "grade": round(max(0.0, grade), 1),
            "reading_ease": round(min(100.0, max(0.0, ease)), 1)}


def grade(text: str) -> float:
    return stats(text)["grade"]
