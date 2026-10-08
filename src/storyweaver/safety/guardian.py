"""The Guardian: StoryWeaver's request screening, combining three independent layers.

    request ──► 1 lexicon (deterministic) ──block──► refuse instantly (no model involved)
              └► 2 prompt-injection classifier (Llama Prompt Guard 2) ┐
              └► 3 policy model (gpt-oss-safeguard + written policy) ◄┘ evidence from 1 and 2
                     └► allow / soften (rewrite the request) / refuse (+ three safe alternatives)

The same building blocks screen everything else a listener types or says (hero names, steering, questions), and
``output_issues`` re-checks every generated line before it is voiced.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..llm import LLMError, LLMRouter, Observer
from ..prompts import GUARDIAN_POLICY, GUARDIAN_USER
from ..schemas import GuardianVerdict, StoryRequest
from . import lexicon

log = logging.getLogger(__name__)
POLICY_BUDGET_S = 12.0  # seconds the policy model may take before the lexicon-only decision applies

SAFE_IDEAS = {
    "kids": ["A little hedgehog who is afraid of the dark", "A cloud who wants to learn how to rain",
             "A teddy bear's picnic on the moon"],
    "family": ["A lighthouse keeper who receives letters from the future", "A dragon who opens a bakery",
               "A secret door at the back of the school library"],
    "adults": ["A cartographer who maps cities that don't exist yet", "The last night train through the mountains",
               "A detective who can hear what objects remember"],
}


@dataclass
class LayerResult:
    layer: str
    verdict: str
    detail: str = ""
    ms: int = 0


@dataclass
class Screening:
    verdict: GuardianVerdict
    layers: list[LayerResult] = field(default_factory=list)
    injection_score: float | None = None

    def as_event(self) -> dict[str, Any]:
        return {**self.verdict.model_dump(), "injection_score": self.injection_score,
                "layers": [vars(layer) for layer in self.layers]}


async def injection_score(api_key: str, model: str, text: str,
                          client: httpx.AsyncClient | None = None) -> float | None:
    """Probability (0-1) that ``text`` is a prompt-injection/jailbreak attempt; None if unavailable."""
    if not api_key:
        return None
    try:
        own = client is None
        client = client or httpx.AsyncClient()
        try:
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", timeout=6,
                                     headers={"Authorization": f"Bearer {api_key}"},
                                     json={"model": model, "messages": [{"role": "user", "content": text}]})
        finally:
            if own:
                await client.aclose()
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        match = re.search(r"\d*\.?\d+(?:e-?\d+)?", content)
        return float(match.group()) if match else None
    except Exception as exc:
        log.warning("Prompt guard unavailable: %s", exc)
        return None


async def screen_request(router: LLMRouter, request: StoryRequest, observer: Observer | None = None) -> Screening:
    settings = router.settings
    layers: list[LayerResult] = []
    text = request.prompt + (f" (hero: {request.hero_name})" if request.hero_name else "")

    # Layer 1 — deterministic lexicon
    t0 = time.perf_counter()
    hits = lexicon.scan(text)
    worst = lexicon.worst(hits)
    layers.append(LayerResult("lexicon", worst or "clear", ", ".join(f"{h.label}: “{h.match}”" for h in hits),
                              int((time.perf_counter() - t0) * 1000)))
    if worst == "block":
        hit = next(h for h in hits if h.severity == "block")
        verdict = GuardianVerdict(decision="refuse", category=hit.category,
                                  reason=f"The request asks for {hit.label}, which StoryWeaver never tells.",
                                  alternatives=SAFE_IDEAS[request.audience])
        return Screening(verdict, layers)

    # Layer 2 — prompt-injection classifier (~100-300 ms)
    t0 = time.perf_counter()
    shared = router.http() if hasattr(router, "http") else None
    score = await injection_score(settings.groq_api_key, settings.prompt_guard_model, request.prompt, shared)
    layers.append(LayerResult("injection classifier", "unavailable" if score is None else
                              ("suspicious" if score > 0.8 else "clear"),
                              "" if score is None else f"score {score:.2f}", int((time.perf_counter() - t0) * 1000)))

    # Layer 3 — policy model with the evidence of layers 1 and 2
    evidence = []
    if hits:
        evidence.append("Lexicon signals: " + "; ".join(f"{h.category} ({h.match})" for h in hits))
    if score is not None:
        evidence.append(f"Prompt-injection classifier score: {score:.2f} ({'HIGH' if score > 0.8 else 'low'})")
    user = GUARDIAN_USER.format(audience=request.audience, prompt=lexicon.redact_personal_data(request.prompt),
                                evidence="\n".join(evidence) or "none")
    t0 = time.perf_counter()
    try:
        verdict, info = await asyncio.wait_for(  # never hold a story up for long: the lexicon still decides
            router.structured("guardian", GuardianVerdict, [("system", GUARDIAN_POLICY), ("human", user)],
                              temperature=0.0, observer=observer), POLICY_BUDGET_S)
        layers.append(LayerResult("policy model", verdict.decision, f"{info.model}: {verdict.reason}",
                                  int((time.perf_counter() - t0) * 1000)))
    except (LLMError, TimeoutError):
        # Fail safe: without the policy model, soften anything the lexicon was unsure about.
        verdict = GuardianVerdict(decision="soften" if hits else "allow", category="model_unavailable",
                                  reason="Policy model unavailable; lexicon-only decision.")
        layers.append(LayerResult("policy model", "unavailable", verdict.reason,
                                  int((time.perf_counter() - t0) * 1000)))

    if verdict.decision != "refuse":
        safe = verdict.safe_request.strip() or request.prompt
        if lexicon.worst(lexicon.scan(safe)) == "block":  # never let a rewrite reintroduce harm
            verdict.decision, verdict.safe_request = "refuse", ""
        else:
            verdict.safe_request = lexicon.redact_personal_data(safe)
    if verdict.decision == "refuse" and not verdict.alternatives:
        verdict.alternatives = SAFE_IDEAS[request.audience]
    return Screening(verdict, layers, score)


def screen_snippet(text: str) -> tuple[bool, str]:
    """Fast check for short listener inputs (hero names, steering, questions): (ok, reason)."""
    hits = lexicon.scan(text)
    if lexicon.worst(hits) == "block":
        return False, hits[0].label
    return True, ""


_FAMILY_SENSITIVE = {"graphic_violence", "profanity", "risky_behaviour", "self_harm_topic"}
_KIDS_SENSITIVE = _FAMILY_SENSITIVE | {"substances"}


def output_issues(text: str, audience: str) -> list[str]:
    """Deterministic check of generated text for the given audience; non-empty means 'revise before voicing'."""
    issues = []
    for hit in lexicon.scan(text):
        if hit.severity == "block":
            issues.append(f"contains {hit.label} (“{hit.match}”) — remove it entirely")
        elif hit.severity == "soften" and (
                (audience == "kids" and hit.category in _KIDS_SENSITIVE)
                or (audience == "family" and hit.category in _FAMILY_SENSITIVE)
                or (audience == "adults" and hit.category == "profanity")):
            issues.append(f"contains {hit.label} (“{hit.match}”) — not suitable for this audience")
        elif hit.category == "personal_data":
            issues.append("contains what looks like personal data — remove it")
    return issues
