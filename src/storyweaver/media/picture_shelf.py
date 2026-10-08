"""The picture shelf: ready-made storybook backdrops that ship with the app.

When every live painter is out of free quota (Cloudflare's daily allowance spent, Pollinations refusing), a scene
still gets a real illustration: the backdrop whose keywords best match the scene's description. The pictures show
places, not characters, so any story can use them. They are painted once with ``scripts/make_picture_shelf.py``
and served from disk: instant, unlimited, and they work offline and on Vercel.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path(__file__).with_name("shelf_pictures")

STYLE = ("soft watercolour and gouache children's picture-book illustration, warm gentle light, rich detail, "
         "wide establishing shot, no people, no animals, no text, no letters, no watermark")


@dataclass(frozen=True)
class Backdrop:
    id: str
    tags: frozenset[str]
    scene: str

    @property
    def prompt(self) -> str:
        return f"{self.scene}. {STYLE}."

    @property
    def path(self) -> Path:
        return FOLDER / f"{self.id}.jpg"


def _b(name: str, tags: str, scene: str) -> Backdrop:
    return Backdrop(name, frozenset(tags.split()), scene)


NIGHT = frozenset({
    "night", "moon", "moonlight", "moonlit", "dark", "darkness", "star", "stars", "starry", "evening",
    "dusk", "midnight", "bedtime", "sleep", "asleep", "dream", "dreams", "lantern", "lanterns", "owl",
})

SHELF = [
    _b("forest", "forest woods wood trees tree path glade clearing woodland oak pine leaves walk",
       "A sunlit forest path winding between tall friendly trees, ferns and wildflowers"),
    _b("forest_night", "forest woods wood trees tree path woodland owl night moon dark moonlit fireflies",
       "A quiet forest at night, moonlight between the trees, fireflies glowing above a mossy path"),
    _b("meadow", "meadow field grass flowers hill hills picnic butterfly sunny spring countryside",
       "A rolling green meadow full of spring flowers under a bright blue sky with puffy clouds"),
    _b("farm", "farm barn tractor hay field orchard fence cow sheep hen pig apples",
       "A red barn and a small farm with hay bales, an orchard and a wooden fence on a sunny morning"),
    _b("garden", "garden flowers vegetables greenhouse grow seed seeds plant plants bloom roses watering",
       "A cheerful cottage garden with vegetable beds, roses, a watering can and a little greenhouse"),
    _b("village", "village town street market cottage cottages houses square shop shops neighbours",
       "A cosy village square with crooked cottages, a market stall and bunting across the street"),
    _b("village_night", "village town street cottage cottages houses night lanterns lantern windows evening",
       "A sleepy village at night, warm lit windows and lanterns glowing under a starry sky"),
    _b("home", "home house room kitchen bedroom bed cosy fireplace fire armchair window family blanket",
       "A cosy room inside a cottage with a crackling fireplace, an armchair, a blanket and a round window"),
    _b("bedroom_night", "bedroom bed bedtime sleep asleep dream night moon toys pillow window quilt",
       "A child's bedroom at bedtime, moonlight through the window falling on a patchwork quilt and toys"),
    _b("bakery", "bakery bread cake cakes oven baking bake baker pie pies cookies kitchen flour pastry",
       "A warm little bakery with loaves, cakes and pies on wooden shelves and a glowing brick oven"),
    _b("castle", "castle king queen princess prince palace tower towers knight kingdom throne royal flags",
       "A storybook castle with tall towers and colourful flags on a green hill"),
    _b("mountain", "mountain mountains peak climb cliff cliffs valley rocks trail summit high",
       "Majestic mountains with a winding trail, a waterfall and a green valley below"),
    _b("snow", "snow snowy winter ice icy frozen cold sled snowman frost december",
       "A snowy winter landscape with frosted pine trees, a frozen pond and soft falling snow"),
    _b("beach", "beach sea ocean shore waves sand sandy shell shells sunny seaside tide",
       "A sunny beach with gentle waves, seashells on the sand and a bright sky"),
    _b("ship", "ship boat sail sailing voyage sea ocean pirate pirates waves deck island captain",
       "A wooden sailing ship on a sparkling blue sea, heading towards a small green island"),
    _b("sea_night", "sea ocean waves night moon moonlit stars boat dark",
       "A calm sea at night, moonlight shimmering on the waves under a sky full of stars"),
    _b("lighthouse", "lighthouse harbour harbor keeper lamp light cliff coast letters gulls",
       "A white lighthouse on a rocky coast beside a little harbour, its lamp shining at dusk"),
    _b("underwater", "underwater reef coral fish mermaid whale octopus deep dive diving turtle bubbles",
       "A bright coral reef under the sea with sunbeams, bubbles and swaying seaweed"),
    _b("island", "island treasure palm palms lagoon tropical shipwreck map",
       "A small tropical island with palm trees and a turquoise lagoon"),
    _b("river", "river stream brook bridge pond lake frog duck ducks reeds raft water",
       "A gentle river with a little stone bridge, reeds, lily pads and stepping stones"),
    _b("desert", "desert dune dunes sand camel oasis cactus hot sun pyramid",
       "Golden desert dunes with a small palm oasis under a wide sunset sky"),
    _b("jungle", "jungle rainforest vines parrot monkey tiger explore explorer waterfall leaves",
       "A lush green jungle with giant leaves, hanging vines and a misty waterfall"),
    _b("cave", "cave caves tunnel underground crystal crystals mine lair dragon glow echo",
       "A glowing cave full of shining crystals and a soft light at the end of a tunnel"),
    _b("sky", "sky clouds cloud fly flying flew balloon bird birds kite wind wings soar air",
       "A wide sky of fluffy clouds with a hot-air balloon and a colourful kite far below the sun"),
    _b("space", "space star stars planet planets rocket astronaut galaxy comet orbit alien spaceship",
       "Outer space with colourful planets, a ringed planet and a little rocket among twinkling stars"),
    _b("starry_hill", "night stars starry moon sky hill wish dream dreams dark wishes shooting",
       "A grassy hill under a huge starry night sky with a crescent moon and a shooting star"),
    _b("library", "library book books map maps mapmaker scroll study read reading story stories letter",
       "A cosy old library with tall bookshelves, rolled maps, a globe and a reading lamp"),
    _b("school", "school class classroom teacher lesson desk friends learn learning blackboard",
       "A bright friendly classroom with little desks, drawings on the wall and a big window"),
    _b("city", "city streets street buildings bus traffic skyscraper skyscrapers park rooftop",
       "A colourful storybook city with rooftops, a park and a red bus on a sunny day"),
    _b("train", "train railway rails station journey travel ticket platform tracks",
       "A little steam train crossing a bridge through green hills on a sunny day"),
    _b("workshop", "workshop invent inventor invention robot robots machine gears tools clock toy toys build",
       "A cluttered inventor's workshop with gears, tools, clocks and half-built toy robots"),
    _b("magic", "magic magical fairy fairies spell spells wizard witch enchanted glow mushroom mushrooms potion",
       "An enchanted glade with glowing mushrooms, sparkling lights and a fairy ring"),
    _b("storm", "storm stormy rain thunder lightning wind windy clouds grey puddles",
       "A rainy stormy day over the hills, dark clouds and a rainbow beginning to appear"),
    _b("autumn", "autumn fall leaves harvest pumpkin pumpkins orange golden apples",
       "An autumn lane with golden and orange leaves, pumpkins and a wooden gate"),
    _b("festival", "festival party birthday celebration celebrate fair music parade dance balloons lights",
       "A joyful festival with string lights, balloons, bunting and a little bandstand"),
    _b("playground", "playground park swing swings slide friends play playing games",
       "A sunny park playground with swings, a slide and a big shady tree"),
]
_BY_ID = {b.id: b for b in SHELF}
DEFAULT = "meadow"


def _words(text: str) -> set[str]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return words | {w[:-1] for w in words if len(w) > 3 and w.endswith("s")}


def ready() -> list[str]:
    return [b.id for b in SHELF if b.path.exists()]


def pick(description: str) -> Backdrop | None:
    """The painted backdrop that best fits the description (None if the shelf has not been painted yet)."""
    words = _words(description)
    night = bool(words & NIGHT)
    best: list[tuple[float, Backdrop]] = []
    for b in SHELF:
        if not b.path.exists():
            continue
        score = len(words & b.tags) + (0.5 if night and b.tags & NIGHT else 0.0)
        best.append((score, b))
    if not best:
        return None
    top = max(score for score, _ in best)
    if top == 0:
        fallback = _BY_ID[DEFAULT]
        return fallback if fallback.path.exists() else best[0][1]
    # several equally good backdrops: vary by description, so two scenes in one story rarely share a picture
    tied = [b for score, b in best if score == top]
    return tied[int(hashlib.sha1(description.encode()).hexdigest(), 16) % len(tied)]


def sources() -> dict[str, str]:
    """Which painter made each backdrop (from ``sources.json``, written by the painting script)."""
    try:
        return json.loads((FOLDER / "sources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
