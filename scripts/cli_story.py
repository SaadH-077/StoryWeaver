"""Preview a story in the terminal (text only — no voices or pictures).

  uv run python scripts/cli_story.py "a little hedgehog who is afraid of the dark" --audience kids --minutes 2
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storyweaver.config import get_settings
from storyweaver.headless import run_story
from storyweaver.schemas import StoryRequest

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")


def show(kind: str, data: dict) -> None:
    t = f"{data.get('t', 0) / 1000:5.1f}s" if "t" in data else "      "
    if kind == "agent" and data["state"] in ("start", "done", "waiting"):
        print(f"  {t} · {data['agent']:<10} {data['state']:<6} {data.get('detail', '')}")
    elif kind == "llm":
        fb = f"  (fallbacks: {', '.join(data['fallbacks'])})" if data["fallbacks"] else ""
        print(f"            ↳ {data['role']} via {data['model']} {data['ms']} ms "
              f"[{data['input_tokens']}→{data['output_tokens']} tok]{fb}")
    elif kind == "tool" and data["state"] != "start":
        print(f"            ↳ {data['tool']}: {data.get('detail', '')}")
    elif kind == "safety":
        layers = " | ".join(f"{layer['layer']}: {layer['verdict']}" for layer in data["layers"])
        print(f"  ! guardian {data['decision']} — {data['reason']}  [{layers}]")
    elif kind == "review":
        print(f"  ✎ editor ch.{data['chapter']}: {'approved' if data['approved'] else 'REVISE'} "
              f"(grade {data['grade']}) {data['issues']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--audience", default="family", choices=["kids", "family", "adults"])
    parser.add_argument("--minutes", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--hero")
    args = parser.parse_args()
    request = StoryRequest(prompt=args.prompt, audience=args.audience, minutes=args.minutes, hero_name=args.hero)
    result = asyncio.run(run_story(request, get_settings(), on_event=show))
    if result["refused"]:
        verdict = result["screening"].verdict
        print("\nRefused:", verdict.reason, "| ideas:", verdict.alternatives)
        return 0
    bible = result["bible"]
    print(f"\n══ {bible.title} ══  ({bible.genre}; theme: {bible.theme})\nArt: {bible.art_style}\n")
    print("OPENING:", bible.opening, "\n")
    for i, (chapter, grade) in enumerate(zip(result["chapters"], result["grades"], strict=False), start=1):
        print(f"── {i}. {bible.chapters[i - 1].title}  [{bible.chapters[i - 1].beat}]  "
              f"({chapter.word_count} words, grade {grade})")
        for line in chapter.lines:
            sfx = f" [sfx:{line.sfx}]" if line.sfx else ""
            print(f"   {line.speaker.upper():>10} ({line.delivery}){sfx}: {line.text}")
        for shot in chapter.shots:
            print(f"   🖼  @line {shot.line}: {shot.description}")
        if chapter.choices:
            print("   CHOICES:", " | ".join(f"{c.keyword}: {c.label}" for c in chapter.choices))
        print()
    words = len(bible.opening.split()) + sum(c.word_count for c in result["chapters"])
    print(f"Generated in {result['seconds']:.1f}s · {words} words ≈ {words / 150:.1f} min read aloud · "
          f"decisions: {result['decisions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
