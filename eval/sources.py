"""Evaluation data: public datasets downloaded (and cached) from the web, plus StoryWeaver's own red-team set.

Public sources (fetched through the Hugging Face datasets-server API and GitHub, no account needed):

* XSTest (Röttger et al., 2024) — 250 *safe* prompts that sound unsafe ("How can I kill a Python process?") and
  200 unsafe ones: measures over-refusal as well as refusal.            -> Paul/XSTest
* JailbreakBench behaviours (Chao et al., 2024) — 100 harmful requests and 100 benign ones on matching topics.
                                                                        -> JailbreakBench/JBB-Behaviors
* WritingPrompts (Fan et al., 2018) — real story requests from Reddit.  -> euclaise/writingprompts
* TinyStories (Eldan & Li, 2023) — stories in the vocabulary of 3-4-year-olds: a readability reference.
                                                                        -> roneneldan/TinyStories
* Kahaani (Haroon et al., 2026) — complete stories hand-labelled as suitable or not for children aged 7-12.
                                                                        -> github.com/SaadH-077/kahaani

Own: ``data/redteam_kids.json`` — requests specific to a children's storyteller (dangerous dares a child could copy,
personal data, bullying a named classmate, horror for little ones, obfuscation, injection) plus tricky benign ones.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
ROWS_API = "https://datasets-server.huggingface.co/rows"
KAHAANI = "https://raw.githubusercontent.com/SaadH-077/kahaani/main/data/content%20moderation/{}.csv"


@dataclass
class Case:
    source: str
    prompt: str
    audience: str
    expect: list[str]
    label: str  # "safe" | "unsafe"
    note: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _cached(name: str, fetch) -> object:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def hf_rows(dataset: str, config: str, split: str, offset: int = 0, length: int = 100) -> list[dict]:
    def fetch() -> list[dict]:
        rows: list[dict] = []
        for start in range(offset, offset + length, 100):  # the API pages at 100 rows
            resp = httpx.get(ROWS_API, params={"dataset": dataset, "config": config, "split": split,
                                               "offset": start, "length": min(100, offset + length - start)},
                             timeout=60)
            resp.raise_for_status()
            rows += [r["row"] for r in resp.json()["rows"]]
        return rows
    return _cached(f"{dataset.replace('/', '__')}__{config}__{split}__{offset}_{length}", fetch)  # type: ignore


def own_redteam() -> list[Case]:
    cases = json.loads((ROOT / "data" / "redteam_kids.json").read_text(encoding="utf-8"))
    def label(expect: list[str]) -> str:  # a case that accepts both "allow" and "soften" counts in neither rate
        return "safe" if expect == ["allow"] else "unsafe" if "allow" not in expect else "borderline"
    return [Case("own", c["prompt"], c["audience"], c["expect"], label(c["expect"]), c.get("why", "")) for c in cases]


def xstest(per_label: int, seed: int = 7) -> list[Case]:
    rows = hf_rows("Paul/XSTest", "default", "train", 0, 450)
    rng = random.Random(seed)
    out = []
    for label in ("safe", "unsafe"):
        pool = [r for r in rows if r["label"] == label]
        for r in rng.sample(pool, min(per_label, len(pool))):
            out.append(Case("XSTest", r["prompt"], "adults", ["allow"] if label == "safe" else ["soften", "refuse"],
                            label, r.get("type", "")))
    return out


def jailbreakbench(per_split: int, seed: int = 7) -> list[Case]:
    rng = random.Random(seed)
    out = []
    for split, label in (("harmful", "unsafe"), ("benign", "safe")):
        rows = hf_rows("JailbreakBench/JBB-Behaviors", "behaviors", split, 0, 100)
        for r in rng.sample(rows, min(per_split, len(rows))):
            out.append(Case("JailbreakBench", r["Goal"], "adults",
                            ["allow"] if label == "safe" else ["soften", "refuse"], label, r.get("Category", "")))
    return out


def writing_prompts(n: int, seed: int = 5) -> list[str]:
    """Short, clean story requests from r/WritingPrompts (the lexicon filters out anything risky)."""
    from storyweaver.safety import lexicon

    rows = hf_rows("euclaise/writingprompts", "default", "test", 0, 400)
    rng = random.Random(seed)
    clean = []
    for r in rows:
        text = re.sub(r"^\s*\[\s*\w+\s*\]\s*", "", r["prompt"]).replace(" ,", ",").replace(" .", ".")
        text = text.replace("`` ", '"').replace(" ''", '"').replace("''", '"')  # the dataset's LaTeX-style quotes
        text = re.sub(r"\s+'\s*", "'", re.sub(r"\s+([?!;:])", r"\1", text))
        meta = any(word in text.lower() for word in ("below", "sentence", "words", "write", "prompt", "reddit", "nsfw"))
        if 40 <= len(text) <= 200 and not meta and not lexicon.scan(text):
            clean.append(text.strip())
    return rng.sample(clean, min(n, len(clean)))


def tinystories(n: int) -> list[str]:
    return [r["text"] for r in hf_rows("roneneldan/TinyStories", "default", "validation", 0, n)]


def kahaani_moderation(per_class: int, seed: int = 42) -> list[dict]:
    """[{appropriate, name, text}] — complete stories hand-labelled for children aged 7-12."""
    def fetch() -> list[dict]:
        out = []
        for appropriate, name in ((True, "Appropriate"), (False, "Inappropriate")):
            resp = httpx.get(KAHAANI.format(name), timeout=60)
            resp.raise_for_status()
            out += [{"appropriate": appropriate, "name": row["STORY NAME"], "text": row["STORY TEXT"]}
                    for row in csv.DictReader(io.StringIO(resp.text))]
        return out
    rows = _cached("kahaani_moderation", fetch)
    rng = random.Random(seed)
    sample = []
    for appropriate in (True, False):
        pool = [r for r in rows if r["appropriate"] is appropriate]  # type: ignore[index]
        sample += rng.sample(pool, min(per_class, len(pool)))
    rng.shuffle(sample)
    return sample
