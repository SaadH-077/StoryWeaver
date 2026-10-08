"""StoryWeaver's own bookshelf: hand-written stories, one per audience, told when no model can deliver in time.

Free tiers have daily limits. A live demo must never fail or stall, so if the Storyteller cannot write a story within
its time budget, StoryWeaver tells one of these — complete with a choice and both endings — and says so honestly in the
crew panel. They go through the same Editor checks, casting, pictures and music as any other story.
"""

from __future__ import annotations

from typing import Any

from .schemas import StoryDraft


def _part(title: str, summary: str, music: str, ambience: list[str], tension: float, lines: list[tuple[str, str, str]],
          shot: str = "", choices: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    return {"title": title, "summary": summary, "music": music, "ambience": ambience, "tension": tension,
            "lines": [{"speaker": s, "text": t, "delivery": d} for s, t, d in lines],
            "shots": [{"line": 0, "description": shot}] if shot else [],
            "choices": [{"keyword": k, "label": label} for k, label in (choices or [])]}


SHELF: dict[str, dict[str, Any]] = {
    "kids": {
        "title": "Pip and the Night Lantern", "logline": "A shy hedgehog learns that the dark is full of friends.",
        "hero_name": "Pip", "hero_look": "a small brown hedgehog with a red knitted scarf",
        "setting": "A meadow by an old oak tree, on a warm summer evening.", "theme": "Being brave together",
        "art_style": "soft watercolour picture-book illustration, warm light",
        "narrator": {"gender": "female", "accent": "british", "style": "warm and gentle"},
        "opening_music": "wonder", "opening_ambience": ["forest"],
        "opening_shot": "A small brown hedgehog with a red scarf under a big oak tree at sunset, fireflies waking up.",
        "opening": ("Once upon a time, under a big old oak tree, lived a little hedgehog named Pip. Pip had a red "
                    "knitted scarf and a nose that loved sweet berries. Every day he rolled in the grass and played "
                    "with the butterflies. But when the sun went down, Pip curled up tight, because Pip was afraid "
                    "of the dark."),
        "question": "Should Pip follow the little light, or wake up his friend Mo the mole?",
        "characters": [
            {"id": "pip", "name": "Pip", "role": "hero", "description": "shy, kind and curious",
             "look": "a small brown hedgehog with a red knitted scarf", "gender": "male", "age": "child"},
            {"id": "mo", "name": "Mo", "role": "friend", "description": "a sleepy, cheerful mole who loves digging",
             "look": "a round grey mole with pink paws and tiny glasses", "gender": "male", "age": "adult"}],
        "parts": [
            _part("A Light in the Dark", "One night Pip sees a tiny light dancing in the meadow.", "mystery",
                  ["night", "forest"], 0.45, [
                      ("narrator", "But one night, a strange thing happened.", "warm"),
                      ("narrator", "A tiny golden light danced past Pip's door, then stopped by the oak tree.", "awe"),
                      ("pip", "Who is there? Hello?", "whisper"),
                      ("narrator", "The light blinked, once, twice, as if it was saying hello.", "warm"),
                      ("pip", "It is so dark out there. But that light is so pretty.", "scared"),
                      ("narrator", "Pip held his red scarf tight. His heart went thump, thump, thump.", "tense"),
                      ("narrator", "The little light bobbed away toward the long grass, slow and gentle.", "calm"),
                      ("narrator", "Down below, under the ground, his friend Mo the mole was fast asleep.", "warm"),
                      ("narrator", "Should Pip follow the little light, or wake up his friend Mo the mole?", "warm")],
                  "A tiny golden light dancing by an old oak tree at night, a small hedgehog peeking out.",
                  [("light", "Follow the little light"), ("mo", "Wake up Mo the mole")]),
            _part("Following the Light", "Pip follows the light and finds a meadow full of fireflies.", "joy",
                  ["night", "forest"], 0.3, [
                      ("narrator", "Pip took one small step into the dark. Then another.", "calm"),
                      ("pip", "I can do this. One step at a time.", "warm"),
                      ("narrator", "The little light waited for him, glowing softly by a blue flower.", "awe"),
                      ("narrator", "It was a firefly! And behind her, the whole meadow began to twinkle.", "excited"),
                      ("pip", "Oh! The dark is full of tiny lanterns!", "excited"),
                      ("narrator", "Pip danced with the fireflies until the moon was high.", "playful"),
                      ("narrator", "He was not scared at all. The dark was not empty. It was full of friends.", "warm"),
                      ("narrator", "And ever since then, Pip goes out every night to say hello to the fireflies.",
                       "warm")],
                  "A happy hedgehog with a red scarf dancing in a meadow full of glowing fireflies under the moon."),
            _part("Waking Mo", "Pip wakes Mo, and together they find the light: a friendly firefly.", "joy",
                  ["night", "forest"], 0.3, [
                      ("narrator", "Pip tapped on Mo's little door, tap, tap, tap.", "playful"),
                      ("mo", "Hmm? Pip? Is it breakfast time?", "playful"),
                      ("pip", "No, Mo. There is a light outside, and I am a bit scared.", "whisper"),
                      ("mo", "Then let's go together. Two friends are braver than one.", "warm"),
                      ("narrator", "Paw in paw, they walked into the dark meadow.", "calm"),
                      ("narrator", "The little light was a firefly, and she had brought all her sisters.", "awe"),
                      ("pip", "Mo, look! The night is beautiful!", "excited"),
                      ("narrator", "And ever since then, whenever the night comes, Pip and Mo watch the fireflies "
                                   "together, and Pip is never afraid.", "warm")],
                  "A hedgehog and a mole holding paws in a twinkling meadow full of fireflies at night."),
        ],
    },
    "family": {
        "title": "The Lighthouse Letters", "logline": "A lighthouse keeper receives letters from tomorrow.",
        "hero_name": "Elsa", "hero_look": "a woman with a yellow raincoat and silver braids",
        "setting": "A lighthouse on a small rocky island.", "theme": "Small kindnesses change the future",
        "art_style": "storybook watercolour, teal sea and warm lamplight",
        "narrator": {"gender": "male", "accent": "british", "style": "warm storyteller"},
        "opening_music": "wonder", "opening_ambience": ["ocean", "wind"],
        "opening_shot": "A tall lighthouse on a rocky island at dusk, a woman in a yellow raincoat on the steps.",
        "opening": ("Once upon a time, on a small rocky island, there stood a tall lighthouse, and in it lived a "
                    "keeper named Elsa. Every evening she climbed one hundred and twelve steps to light the great "
                    "lamp. Her cat, Biscuit, followed her up every single step. Elsa loved the sea, but sometimes "
                    "she wished something surprising would happen."),
        "question": "Should Elsa row out to the fishing boat, or ring the old bell to warn it?",
        "characters": [
            {"id": "elsa", "name": "Elsa", "role": "hero", "description": "brave, careful and a little lonely",
             "look": "a woman with a yellow raincoat and silver braids", "gender": "female", "age": "adult"},
            {"id": "biscuit", "name": "Biscuit", "role": "friend", "description": "a clever ginger cat",
             "look": "a fluffy ginger cat with a white tail tip", "gender": "male", "age": "adult"}],
        "parts": [
            _part("A Letter from Tomorrow", "A bottle brings a letter dated tomorrow, warning of a storm.",
                  "mystery", ["ocean", "wind"], 0.5, [
                      ("narrator", "But one morning, a green bottle bumped against the rocks.", "warm"),
                      ("narrator", "Inside was a letter, and the date on it was tomorrow.", "awe"),
                      ("elsa", "That is impossible. Biscuit, look at this!", "excited"),
                      ("narrator", "The letter said: a little fishing boat will be lost in tonight's storm.", "tense"),
                      ("narrator", "Elsa looked out to sea. Dark clouds were already rolling in.", "tense"),
                      ("biscuit", "Meow.", "playful"),
                      ("narrator", "Biscuit pawed at the window. Far away, a small boat bobbed on the waves.", "tense"),
                      ("elsa", "Whoever wrote this was trying to help. Now it is my turn.", "warm"),
                      ("narrator", "Should Elsa row out to the fishing boat, or ring the old bell to warn it?",
                       "warm")],
                  "A woman in a yellow raincoat reading a letter by a green bottle on rocks, storm clouds coming.",
                  [("row", "Row out to the boat"), ("bell", "Ring the old bell")]),
            _part("Rowing Through the Waves", "Elsa rows out and guides the boat home by lantern.", "triumph",
                  ["ocean", "storm"], 0.7, [
                      ("narrator", "Elsa pulled on her raincoat and pushed her little rowing boat into the sea.",
                       "tense"),
                      ("elsa", "Hold on, Biscuit. We will be quick.", "tense"),
                      ("narrator", "The waves were tall, but Elsa rowed steady and strong.", "tense"),
                      ("narrator", "She lifted her lantern high, and the fishermen saw the light.", "awe"),
                      ("elsa", "Follow me! The harbour is this way!", "excited"),
                      ("narrator", "One by one, they followed her glow, safely home through the storm.", "warm"),
                      ("narrator", "That night, Elsa wrote a letter of her own and put it in the green bottle.",
                       "calm"),
                      ("narrator", "And ever since then, the island has had two lights: the lamp at the top, and "
                                   "Elsa's kindness at the bottom.", "warm")],
                  "A small rowing boat with a raised lantern guiding a fishing boat through stormy waves."),
            _part("The Old Bell", "Elsa rings the old bell and the boat turns home in time.", "triumph",
                  ["ocean", "storm"], 0.6, [
                      ("narrator", "Elsa ran to the old bronze bell that nobody had rung for years.", "excited"),
                      ("elsa", "Biscuit, help me pull!", "excited"),
                      ("narrator", "Together they tugged the rope. Dong! Dong! Dong!", "excited"),
                      ("narrator", "Far away, the fishermen heard the bell and turned toward the island.", "awe"),
                      ("elsa", "They heard it! They are coming home!", "excited"),
                      ("narrator", "The little boat reached the harbour just as the storm began.", "warm"),
                      ("narrator", "Elsa wrapped the fishermen in blankets and gave them hot cocoa.", "warm"),
                      ("narrator", "And ever since then, Elsa rings the bell every evening, just to say: you are "
                                   "never alone on this sea.", "warm")],
                  "A woman and a ginger cat pulling the rope of a big bronze bell at a lighthouse in the rain."),
        ],
    },
    "adults": {
        "title": "The Mapmaker's Last Street", "logline": "A cartographer finds a street that appears on no map.",
        "hero_name": "Marta", "hero_look": "a woman in a long green coat with ink-stained fingers",
        "setting": "An old town of cobbled streets, on a warm spring evening.", "theme": "Some places find us",
        "art_style": "muted ink-and-watercolour, lamplit streets",
        "narrator": {"gender": "female", "accent": "american", "style": "calm and intimate"},
        "opening_music": "mystery", "opening_ambience": ["city", "night"],
        "opening_shot": "A woman in a long green coat studying a map under a street lamp in an old cobbled town.",
        "opening": ("Once, in an old town of crooked lanes, there lived a mapmaker named Marta. She had drawn every "
                    "street, stair and alley, and she knew them the way others know a song. Every night she walked "
                    "her maps to check them. Yet one lane was missing, and every night she heard slow footsteps "
                    "there, as if someone were waiting for her."),
        "question": "Should Marta follow the footsteps, or draw the lane onto her map first?",
        "characters": [
            {"id": "marta", "name": "Marta", "role": "hero", "description": "precise, patient and secretly lonely",
             "look": "a woman in a long green coat with ink-stained fingers", "gender": "female", "age": "adult"},
            {"id": "tomas", "name": "Tomas", "role": "stranger", "description": "an old lamplighter who speaks softly",
             "look": "an old man with a lamplighter's pole and a grey cap", "gender": "male", "age": "elder"}],
        "parts": [
            _part("The Missing Lane", "On the first warm night of spring, the hidden lane appears.", "mystery",
                  ["city", "night"], 0.5, [
                      ("narrator", "On the first warm night of spring, the footsteps came again.", "calm"),
                      ("narrator", "This time, between the bakery and the clockmaker's, there was a gap in the wall.",
                       "awe"),
                      ("marta", "That was never there. I would have drawn it.", "whisper"),
                      ("narrator", "A narrow lane curved away into lamplight. The footsteps paused, then went on.",
                       "tense"),
                      ("marta", "Hello? Who are you?", "tense"),
                      ("narrator", "No one answered, but a lamp at the far end flickered, as if in reply.", "calm"),
                      ("narrator", "Marta looked down at her map. The space between the two shops was blank.", "calm"),
                      ("narrator", "Should Marta follow the footsteps, or draw the lane onto her map first?", "warm")],
                  "A narrow glowing lane appearing between a bakery and a clock shop at night, a woman watching.",
                  [("follow", "Follow the footsteps"), ("draw", "Draw the lane first")]),
            _part("The Lamplighter", "Marta follows and meets the lamplighter who keeps the town's forgotten places.",
                  "calm", ["city", "night"], 0.35, [
                      ("narrator", "Marta stepped into the lane. The cobbles were warm under her feet.", "calm"),
                      ("narrator", "At the end stood an old lamplighter, lighting a lamp that needed no lighting.",
                       "awe"),
                      ("tomas", "You took your time, mapmaker. I have been walking this lane for years.", "warm"),
                      ("marta", "Why does it appear on no map?", "calm"),
                      ("tomas", "Because it only exists for those who notice what is missing.", "warm"),
                      ("narrator", "He handed her his pole. The next lamp was hers to light.", "warm"),
                      ("narrator", "Marta never drew the lane. Some places are meant to be walked, not mapped.",
                       "calm"),
                      ("narrator", "And ever since then, on warm spring nights, two lamplighters walk the old town.",
                       "warm")],
                  "An old lamplighter handing his pole to a woman in a green coat in a warm lamplit lane."),
            _part("The Drawn Lane", "Marta draws the lane, and the map reveals where it leads.", "calm",
                  ["city", "night"], 0.35, [
                      ("narrator", "Marta unrolled her map against the wall and drew the lane, line by careful line.",
                       "calm"),
                      ("narrator", "As the ink dried, the drawing kept going on its own, curling past the edge.",
                       "awe"),
                      ("marta", "It leads somewhere. Somewhere I have never been.", "whisper"),
                      ("narrator", "She followed the new line through the lane to a small square with a fountain.",
                       "calm"),
                      ("tomas", "Welcome. Every map needs one place its maker does not know yet.", "warm"),
                      ("narrator", "The old lamplighter smiled and offered her a seat by the water.", "warm"),
                      ("narrator", "That night Marta learned that a map is never finished, and neither is she.",
                       "calm"),
                      ("narrator", "And ever since then, she leaves one corner of every map blank, on purpose.",
                       "warm")],
                  "A hand-drawn map glowing on an old wall, its ink line curling into a lamplit lane."),
        ],
    },
}


def shelf_story(audience: str, parts: int) -> StoryDraft:
    """A complete hand-written story for this audience, shaped to the parts the structure needs."""
    data = dict(SHELF.get(audience, SHELF["family"]))
    if parts == 1:  # a story without a choice: the beginning and the first ending, without the question
        first, ending = data["parts"][0], data["parts"][1]
        lines = [line for line in first["lines"] if "?" not in line["text"]] + ending["lines"]
        data["parts"] = [{**ending, "title": first["title"], "lines": lines, "choices": [],
                          "shots": ending["shots"]}]
        data["question"] = ""
    return StoryDraft.model_validate(data)
