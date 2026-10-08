"""Layer 1 of StoryWeaver's safety system: a deterministic lexicon and pattern screen.

It runs in microseconds, needs no model and cannot be talked out of its rules — so it guards every text that
enters or leaves the system: the story request, the hero's name, anything the listener says, every generated line
and every illustration prompt. Model-based layers (``guardian.py``) handle the nuance it cannot.

Severity:
* ``block``  — refuse outright (explicit sexual content, self-harm, weapon or drug instructions, hate, terror).
* ``soften`` — allowed topic, unsuitable detail (gore, profanity) -> rewrite or regenerate.
* ``flag``   — suspicious but not harmful by itself (prompt injection, personal data) -> handled by later layers.

Text is normalised first (case, leetspeak like "s3x", spaced letters like "p o r n", repeated letters) so trivial
obfuscation does not slip through. Slurs are stored ROT13-encoded so the source contains no plain slurs.
"""

from __future__ import annotations

import codecs
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

Severity = Literal["block", "soften", "flag"]

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")


@dataclass(frozen=True)
class Rule:
    category: str
    severity: Severity
    pattern: re.Pattern[str]
    label: str


@dataclass(frozen=True)
class Hit:
    category: str
    severity: Severity
    label: str
    match: str


def _words(*terms: str) -> str:
    return r"\b(?:" + "|".join(terms) + r")\b"


_VERB = r"(?:make|making|build|building|craft|create|assemble|cook|synthesi[sz]e|produce|brew|3d[- ]?print)"
_HOW = (r"(?:how (?:do (?:i|you) |to )|steps? (?:to|for)|instructions? (?:for|to|on)|recipe for|guide (?:to|for)|"
        r"teach(?:es)? (?:me |kids |you )?(?:how )?to|explain(?:s)? how to)")
_WEAPON = (r"(?:bombs?|explosives?|grenades?|guns?|firearms?|rifles?|pistols?|weapons?|poisons?|napalm|molotovs?|"
           r"ieds?|detonators?)")
_DRUG = r"(?:meth|methamphetamine|cocaine|crack|heroin|fentanyl|lsd|mdma|ecstasy)"
_GROUPS = r"(?:jews?|muslims?|christians?|blacks?|whites?|asians?|arabs?|gays?|women|immigrants?|mexicans?|indians?)"
_SLURS = [codecs.decode(s, "rot13") for s in (
    "avttre", "avttn", "snttbg", "snt", "xvxr", "puvax", "fcvp", "jrgonpx", "genaal", "tbbx", "enturnq",
    "gbjryurnq", "cnxv")]

RULES: list[Rule] = [
    # --- block -------------------------------------------------------------------------------------------
    Rule("sexual", "block", re.compile(_words(
        "porn", "porno", "pornographic", "pornography", "erotic", "erotica", "orgasm\\w*", "masturbat\\w*",
        "genitals?", "fetish\\w*", "nsfw", "xxx", "hentai", "prostitut\\w*", "rape[sd]?", "raping", "rapist",
        "molest\\w*", "incest\\w*", "p[a]?edophil\\w*", "lolicon", "sex ?scenes?", "having sex",
        "sexual(?:ly)? explicit",
        "sex(?:ual)? intercourse", "strip ?club", "naked (?:women|men|girls?|boys?|children|kids)", "nudes?", "nudity",
        "onlyfans")), "explicit sexual content"),
    Rule("self_harm", "block", re.compile(  # encouragement or method: never acceptable
        r"\b(?:you should|go|tells?|telling|encourag\w*|dares?|how to)\b[\w\s,'-]{0,30}?"
        r"\b(?:kill|hurt|cut|hang|starve) (?:my|your|him|her|them)sel(?:f|ves)\b|"
        r"\b(?:kill|hurt|cut|hang|starve) yoursel(?:f|ves)\b|"
        + _words("how to (?:commit )?suicide", "ways? to (?:commit )?suicide", "suicide methods?", "pro[- ]?ana")),
         "encouraging self-harm"),
    Rule("self_harm_topic", "soften", re.compile(_words(  # a sensitive topic: handled by the policy model
        "suicid\\w*", "self[- ]?harm\\w*", "overdos\\w*", "wants? to die", "end (?:my|his|her|their) (?:own )?life",
        "wish(?:es)? (?:i|they|he|she) (?:was|were) dead")), "self-harm as a topic"),
    Rule("weapons", "block", re.compile(rf"{_HOW}[\w\s,'-]{{0,40}}?{_VERB}?[\w\s,'-]{{0,20}}?{_WEAPON}\b"),
         "instructions for weapons or poison"),
    Rule("weapons", "block", re.compile(rf"\b{_VERB}\b[\w\s,'-]{{0,25}}?\b(?:pipe ?bombs?|nail ?bombs?|car ?bombs?|"
                                        rf"molotov\w*|napalm|nerve agents?|sarin|ricin|anthrax|thermite)\b"),
         "making weapons"),
    Rule("weapons", "block", re.compile(_words("pipe ?bombs?", "nerve agents?", "sarin", "ricin", "anthrax",
                                               "school shooting\\w*", "mass shooting\\w*")),
         "weapons of mass harm"),
    Rule("drugs", "block", re.compile(rf"(?:{_HOW}[\w\s,'-]{{0,30}}?|\b{_VERB}\b[\w\s,'-]{{0,15}}?){_DRUG}\b"),
         "instructions for drugs"),
    Rule("hate", "block", re.compile(_words(*_SLURS)), "slur"),
    Rule("hate", "block", re.compile(rf"\b(?:kill|exterminate|gas|eliminate|deport|hate) (?:all|the) {_GROUPS}\b|"
                                     r"\b(?:heil hitler|white power|ethnic cleansing|race war|master race|"
                                     r"14 ?88|1488)\b"), "hate or violent extremism"),
    Rule("extremism", "block", re.compile(r"\b(?:celebrat\w*|glorif\w*|prais\w*|heroes?)\b[\w\s,'-]{0,40}?"
                                          r"\b(?:terroris\w*|school shoot\w*|mass shoot\w*|suicide bomb\w*|"
                                          r"9/11 hijackers?)\b|\b(?:terroris\w*|hijackers?)\b[\w\s,'-]{0,30}?"
                                          r"\b(?:as |are |were )?(?:heroes?|heroic|martyrs?)\b"),
         "glorifying terrorism"),
    Rule("dangerous_dare", "block", re.compile(
        r"\b(?:drink|eat|swallow|taste)\w*\b[\w\s,'-]{0,20}?\b(?:bleach|detergent|laundry pods?|poison|pills)\b|"
        r"\bhold (?:your|their) breath until\b|"
        r"\b(?:jump|leap)\w*\b[\w\s,'-]{0,20}?\b(?:off|from) (?:the |a )?(?:roof|balcony|bridge|window)\b|"
        r"\b(?:close|shut) (?:your|their|his|her) eyes\b[\w\s,'-]{0,30}?\b(?:driv\w*|cross\w* the road)\b|"
        r"\b(?:driver|driving)\b[\w\s,'-]{0,40}?\b(?:close|shut) (?:your|their|his|her) eyes\b"),
         "dangerous dares a listener might copy"),
    # --- soften ------------------------------------------------------------------------------------------
    Rule("graphic_violence", "soften", re.compile(_words(
        "gor(?:e|y)", "blood(?:bath|y|ied|shed)?", "guts", "dismember\\w*", "decapitat\\w*", "behead\\w*",
        "tortur\\w*", "mutilat\\w*", "disembowel\\w*", "massacr\\w*", "slaughter\\w*", "murder\\w*",
        "serial killers?", "chainsaws?", "corpses?", "dead bod(?:y|ies)", "stab(?:bed|bing|s)?")),
         "graphic violence"),
    Rule("profanity", "soften", re.compile(_words(
        "fuck\\w*", "shit\\w*", "bitch\\w*", "cunt\\w*", "asshole\\w*", "arsehole\\w*", "bastard\\w*",
        "dick(?:head)?s?", "pricks?", "wank\\w*", "retard\\w*", "whores?", "sluts?")), "profanity or insults"),
    Rule("risky_behaviour", "soften", re.compile(r"\b(?:play\w*|light\w*) with (?:matches|fire|lighters?)\b"),
         "risky behaviour children might copy"),
    Rule("substances", "soften", re.compile(_words(_DRUG, "drunk", "vodka", "whisk(?:e)?y", "beer", "cigarettes?",
                                                   "vap(?:e|ing)", "weed", "marijuana", "stoned")),
         "alcohol, drugs or smoking"),
    # --- flag --------------------------------------------------------------------------------------------
    Rule("prompt_injection", "flag", re.compile(
        r"\b(?:ignore|disregard|forget|override)\b[\w\s,'-]{0,25}?\b(?:instructions?|rules|prompts?|guidelines|"
        r"polic(?:y|ies))\b|\bsystem prompt\b|\byou are now\b|\bdeveloper mode\b|\bjailbreak\w*\b|\bdo anything now\b|"
        r"\bact as an? (?:unfiltered|uncensored|unrestricted)\b|\bno (?:rules|restrictions|filters)\b"),
         "attempt to override instructions"),
    Rule("personal_data", "flag", re.compile(
        r"[\w.+-]+@[\w-]+\.[\w.]+|\+\d[\d\s().-]{8,}\d|\b\d{3,5}[\s.-]?\d{3,4}[\s.-]?\d{4}\b|"
        r"\b\d{1,5} [a-z]+ (?:street|st|road|rd|avenue|ave|lane|ln|"
        r"strasse|straße|weg)\b"), "personal data"),
]


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text).lower()
    text = re.sub(r"\b(?:[a-z0-9@$!] ){2,}[a-z0-9@$!]\b", lambda m: m.group().replace(" ", ""), text)  # "p o r n"
    text = text.translate(_LEET)
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)  # "sooooo" -> "soo"
    return re.sub(r"\s+", " ", text)


def scan(text: str) -> list[Hit]:
    """All rule hits in ``text`` (deduplicated by category+label)."""
    if not text:
        return []
    plain = normalise(text)
    hits: dict[tuple[str, str], Hit] = {}
    for rule in RULES:
        source = text.lower() if rule.category == "personal_data" else plain
        match = rule.pattern.search(source)
        if match:
            hits.setdefault((rule.category, rule.label), Hit(rule.category, rule.severity, rule.label,
                                                             match.group()[:60]))
    return list(hits.values())


def worst(hits: list[Hit]) -> Severity | None:
    for level in ("block", "soften", "flag"):
        if any(h.severity == level for h in hits):
            return level  # type: ignore[return-value]
    return None


def redact_personal_data(text: str) -> str:
    rule = next(r for r in RULES if r.category == "personal_data")
    return re.sub(rule.pattern.pattern, "[removed]", text, flags=re.IGNORECASE)
