"""Voice casting: every speaker gets a distinct, fitting voice — for each of the three voice engines.

Casting is plain code rather than an LLM call: instant, free, deterministic for a given story and easy to test.
The bible supplies the inputs (gender, age, accent, personality); the catalogues supply the voices:

* ``edge``   — Microsoft's neural voices, synthesised on the server ("neural": fast, free, no key);
* ``kokoro`` — Kokoro-82M voices for on-device "studio" narration (server);
* ``gemini`` — Gemini TTS prebuilt voices for expressive cloud narration (server);
* ``profile`` — gender/age/accent/pitch hints the browser uses to pick one of the device's neural voices.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from ..schemas import CharacterSpec, NarratorSpec, StoryBible, StoryOpening

# id: (gender, accent, age, quality 1-5) — quality follows the Kokoro-82M voice card grades
KOKORO_VOICES: dict[str, tuple[str, str, str, int]] = {
    "af_heart": ("female", "american", "adult", 5), "af_bella": ("female", "american", "young", 4),
    "af_nicole": ("female", "american", "adult", 3), "af_aoede": ("female", "american", "adult", 3),
    "af_kore": ("female", "american", "adult", 3), "af_sarah": ("female", "american", "adult", 3),
    "af_nova": ("female", "american", "young", 2), "af_sky": ("female", "american", "young", 2),
    "af_alloy": ("female", "american", "adult", 2), "af_jessica": ("female", "american", "young", 2),
    "af_river": ("female", "american", "adult", 2), "am_michael": ("male", "american", "adult", 3),
    "am_fenrir": ("male", "american", "adult", 3), "am_puck": ("male", "american", "young", 3),
    "am_echo": ("male", "american", "adult", 2), "am_eric": ("male", "american", "adult", 2),
    "am_liam": ("male", "american", "young", 2), "am_onyx": ("male", "american", "elder", 2),
    "am_santa": ("male", "american", "elder", 1), "bf_emma": ("female", "british", "adult", 4),
    "bf_isabella": ("female", "british", "adult", 3), "bf_alice": ("female", "british", "adult", 2),
    "bf_lily": ("female", "british", "young", 2), "bm_george": ("male", "british", "elder", 3),
    "bm_fable": ("male", "british", "adult", 3), "bm_lewis": ("male", "british", "adult", 2),
    "bm_daniel": ("male", "british", "adult", 2),
}

# Microsoft neural voices (via edge-tts): id: (gender, accent, age)
EDGE_VOICES: dict[str, tuple[str, str, str]] = {
    "en-US-AvaNeural": ("female", "american", "adult"), "en-US-EmmaNeural": ("female", "american", "adult"),
    "en-US-JennyNeural": ("female", "american", "adult"), "en-US-AriaNeural": ("female", "american", "adult"),
    "en-US-MichelleNeural": ("female", "american", "adult"), "en-US-AnaNeural": ("female", "american", "child"),
    "en-US-AndrewNeural": ("male", "american", "adult"), "en-US-BrianNeural": ("male", "american", "adult"),
    "en-US-GuyNeural": ("male", "american", "adult"), "en-US-ChristopherNeural": ("male", "american", "adult"),
    "en-US-EricNeural": ("male", "american", "adult"), "en-US-SteffanNeural": ("male", "american", "adult"),
    "en-US-RogerNeural": ("male", "american", "elder"), "en-GB-SoniaNeural": ("female", "british", "adult"),
    "en-GB-LibbyNeural": ("female", "british", "adult"), "en-GB-MaisieNeural": ("female", "british", "child"),
    "en-GB-RyanNeural": ("male", "british", "adult"), "en-GB-ThomasNeural": ("male", "british", "elder"),
    "en-AU-NatashaNeural": ("female", "british", "adult"), "en-IE-ConnorNeural": ("male", "british", "adult"),
    "en-IE-EmilyNeural": ("female", "british", "adult"), "en-CA-ClaraNeural": ("female", "american", "adult"),
    "en-CA-LiamNeural": ("male", "american", "adult"),
}

NARRATOR_EDGE = {("female", "british"): "en-GB-SoniaNeural", ("male", "british"): "en-GB-RyanNeural",
                 ("female", "american"): "en-US-EmmaNeural", ("male", "american"): "en-US-AndrewNeural"}

# Gemini TTS prebuilt voices: id: gender
GEMINI_VOICES: dict[str, str] = {
    "Zephyr": "female", "Puck": "male", "Charon": "male", "Kore": "female", "Fenrir": "male", "Leda": "female",
    "Orus": "male", "Aoede": "female", "Callirrhoe": "female", "Autonoe": "female", "Enceladus": "male",
    "Iapetus": "male", "Umbriel": "male", "Algieba": "male", "Despina": "female", "Erinome": "female",
    "Algenib": "male", "Rasalgethi": "male", "Laomedeia": "female", "Achernar": "female", "Alnilam": "male",
    "Schedar": "male", "Gacrux": "female", "Pulcherrima": "female", "Achird": "male", "Zubenelgenubi": "male",
    "Vindemiatrix": "female", "Sadachbia": "male", "Sadaltager": "male", "Sulafat": "female",
}

# Delivery -> speaking-rate multiplier and pitch (the browser engine can shift pitch; Kokoro uses rate only)
DELIVERY_SPEED = {"neutral": 1.0, "warm": 0.97, "calm": 0.94, "excited": 1.08, "playful": 1.05,
                  "whisper": 0.9, "tense": 1.04, "scared": 1.06, "sad": 0.9, "awe": 0.93}
DELIVERY_STYLE = {"neutral": "natural storytelling", "warm": "warm and kind", "calm": "calm and measured",
                  "excited": "excited and lively", "playful": "playful, with a smile",
                  "whisper": "a hushed, close whisper", "tense": "tense and urgent",
                  "scared": "frightened, breathless", "sad": "sad and soft", "awe": "full of wonder, hushed"}


@dataclass(frozen=True)
class Voice:
    kokoro: str
    gemini: str
    edge: str = "en-US-AvaNeural"
    gender: str = "female"
    age: str = "adult"
    accent: str = "british"
    speed: float = 1.0
    pitch: float = 1.0
    persona: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


HOST = Voice("af_heart", "Sulafat", "en-US-AvaNeural", "female", "adult", "american", 1.0, 1.0,
              "the friendly StoryWeaver host")


def _rank(seed: str, voice_id: str) -> int:
    return int(hashlib.sha1(f"{seed}:{voice_id}".encode()).hexdigest()[:8], 16)


def _pick_kokoro(gender: str, accent: str, age: str, used: set[str], seed: str) -> str:
    want_age = {"child": "young", "teen": "young", "adult": "adult", "elder": "elder"}[age]

    def score(item: tuple[str, tuple[str, str, str, int]]) -> tuple[int, int, int, int, int]:
        vid, (g, a, vage, quality) = item
        return (int(gender == "neutral" or g == gender), int(a == accent), int(vage == want_age), quality,
                _rank(seed, vid))

    candidates = [item for item in KOKORO_VOICES.items() if item[0] not in used]
    return max(candidates, key=score)[0] if candidates else HOST.kokoro


def _pick_edge(gender: str, accent: str, age: str, used: set[str], seed: str) -> str:
    want_age = "child" if age in ("child", "teen") else age

    def score(item: tuple[str, tuple[str, str, str]]) -> tuple[int, int, int, int]:
        vid, (g, a, vage) = item
        return (int(gender == "neutral" or g == gender), int(vage == want_age) * 2 - int(vage == "child"),
                int(a == accent), _rank(seed, vid))

    candidates = [item for item in EDGE_VOICES.items() if item[0] not in used]
    return max(candidates, key=score)[0] if candidates else HOST.edge


def _pick_gemini(gender: str, used: set[str], seed: str) -> str:
    candidates = [vid for vid, g in GEMINI_VOICES.items() if vid not in used and (gender == "neutral" or g == gender)]
    candidates = candidates or [vid for vid in GEMINI_VOICES if vid not in used] or list(GEMINI_VOICES)
    return max(candidates, key=lambda vid: _rank(seed, vid))


def _narrator(n: NarratorSpec, audience: str, seed: str, used_g: set[str]) -> Voice:
    if audience == "kids":
        kokoro = "bf_emma" if n.accent == "british" else "af_bella"
    else:
        kokoro = {("female", "british"): "bf_emma", ("male", "british"): "bm_george",
                  ("female", "american"): "af_bella", ("male", "american"): "am_michael"}[(n.gender, n.accent)]
    gemini = _pick_gemini(n.gender, used_g, seed)
    used_g.add(gemini)
    edge = NARRATOR_EDGE[(n.gender, n.accent)]
    return Voice(kokoro, gemini, edge, n.gender, "adult", n.accent, 0.97, 1.0, n.style)


def _character(c: CharacterSpec, used_k: set[str], used_g: set[str], seed: str,
               used_e: set[str] | None = None) -> Voice:
    used_e = used_e if used_e is not None else set()
    kokoro = _pick_kokoro(c.gender, c.accent, c.age, used_k, seed + c.id)
    gemini = _pick_gemini(c.gender, used_g, seed + c.id)
    edge = _pick_edge(c.gender, c.accent, c.age, used_e, seed + c.id)
    used_k.add(kokoro)
    used_g.add(gemini)
    used_e.add(edge)
    speed = 1.06 if c.age == "child" else 0.95 if c.age == "elder" else 1.0
    pitch = 1.15 if c.age == "child" else 0.9 if c.age == "elder" else 1.0
    persona = f"{c.name}, {c.age} {c.role}: {c.description}"[:160]
    return Voice(kokoro, gemini, edge, c.gender, c.age, c.accent, speed, pitch, persona)


def cast_opening(opening: StoryOpening, audience: str) -> dict[str, Voice]:
    """The host and the narrator — all the opening needs. ``cast`` later gives them the very same voices."""
    return {"host": HOST, "narrator": _narrator(opening.narrator, audience, opening.title, {HOST.gemini})}


def cast(bible: StoryBible, audience: str) -> dict[str, Voice]:
    """Assign a voice to the host, the narrator and every character. Deterministic per story title."""
    seed = bible.title
    voices = cast_opening(bible, audience)
    used_k = {HOST.kokoro, voices["narrator"].kokoro}
    used_g = {HOST.gemini, voices["narrator"].gemini}
    used_e = {HOST.edge, voices["narrator"].edge}
    for character in bible.characters:
        voices[character.id] = _character(character, used_k, used_g, seed, used_e)
    return voices


def voice_for_extra(speaker_id: str, voices: dict[str, Voice], seed: str) -> Voice:
    """A walk-on speaker the bible did not plan for gets an unused voice (and keeps it)."""
    if speaker_id in voices:
        return voices[speaker_id]
    used_k = {v.kokoro for v in voices.values()}
    used_g = {v.gemini for v in voices.values()}
    used_e = {v.edge for v in voices.values()}
    voice = Voice(_pick_kokoro("neutral", "american", "adult", used_k, seed + speaker_id),
                  _pick_gemini("neutral", used_g, seed + speaker_id),
                  _pick_edge("neutral", "american", "adult", used_e, seed + speaker_id), "neutral", "adult", "american",
                  persona=speaker_id.replace("_", " "))
    voices[speaker_id] = voice
    return voice
