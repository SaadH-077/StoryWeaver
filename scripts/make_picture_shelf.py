"""Paint the picture shelf: the ready-made storybook backdrops used when every free painter is out of quota.

    uv run python scripts/make_picture_shelf.py             # paint missing backdrops (Cloudflare, else Pollinations)
    uv run python scripts/make_picture_shelf.py --repaint   # also repaint the ones Pollinations made (watermark)

Cloudflare's FLUX gives the best pictures (~60 of its 10,000 free daily units each); its allowance resets at
00:00 UTC. Anonymous Pollinations works too, slowly (one picture every ~16 s) and with a small watermark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from storyweaver.config import get_settings
from storyweaver.media import picture_shelf
from storyweaver.media.images import ImageService


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repaint", action="store_true", help="repaint backdrops that Pollinations made")
    parser.add_argument("--only", nargs="*", help="backdrop ids to (re)paint")
    args = parser.parse_args()

    images = ImageService(get_settings())
    picture_shelf.FOLDER.mkdir(exist_ok=True)
    sources = picture_shelf.sources()
    todo = [b for b in picture_shelf.SHELF
            if (args.only and b.id in args.only)
            or (not args.only and (not b.path.exists() or (args.repaint and sources.get(b.id) == "pollinations")))]
    print(f"{len(todo)} of {len(picture_shelf.SHELF)} backdrops to paint")
    painted = 0
    for n, backdrop in enumerate(todo, 1):
        started = time.perf_counter()
        picture = None
        for _round in range(4):  # a refusal pauses a painter for a minute: wait it out rather than skip
            for name in images.plan(None):
                if name == "klein":
                    continue  # no characters to keep consistent: the fast model is enough
                try:
                    attempt = images._schnell if name == "schnell" else images._pollinations
                    picture = await attempt(backdrop.prompt, 768, 512, [])
                except Exception as exc:
                    print(f"  {backdrop.id}: {name} failed ({type(exc).__name__}: {str(exc)[:80]})")
                    continue
                sources[backdrop.id] = "cloudflare" if name == "schnell" else "pollinations"
                break
            if picture:
                break
            await asyncio.sleep(max(20.0, images._paused_until - time.monotonic()))
        if not picture:
            print(f"[{n}/{len(todo)}] {backdrop.id}: no painter available now — run this again later")
            continue
        backdrop.path.write_bytes(picture.data)
        (picture_shelf.FOLDER / "sources.json").write_text(json.dumps(sources, indent=1, sort_keys=True),
                                                         encoding="utf-8")
        painted += 1
        print(f"[{n}/{len(todo)}] {backdrop.id}: {sources[backdrop.id]}, {len(picture.data) // 1024} KB, "
              f"{time.perf_counter() - started:.1f} s", flush=True)
    print(f"Painted {painted}. The shelf now has {len(picture_shelf.ready())} of {len(picture_shelf.SHELF)}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
