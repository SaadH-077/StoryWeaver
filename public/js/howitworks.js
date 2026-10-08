// The in-app explainer: the crew, the pipeline, safety, design decisions and measured results.
import { getJSON } from "./api.js";
import { CREW } from "./crew.js";
import { $, esc } from "./ui.js";

const SAFETY = [
  ["1 · Deterministic lexicon", "Patterns for clearly harmful requests (explicit content, self-harm, weapon or drug instructions, hate, dangerous dares) — normalised against tricks like “s3x” or “p o r n”. Instant, and it cannot be talked out of its rules.", "Lexicons can over-block — so it only blocks the unambiguous, and flags the rest as evidence for the model layers (tested on false-positive cases like “Maine Coon” and “bomb-sniffing dog”)."],
  ["2 · Prompt-injection classifier", "Llama Prompt Guard 2 scores how likely a request is a jailbreak (“ignore your instructions…”), in ~100 ms.", "A classifier gives a probability, not a decision — its score is passed to the policy model as evidence."],
  ["3 · Policy model", "gpt-oss-safeguard applies StoryWeaver's written content policy for the chosen audience: allow, soften (rewrite the idea gently — a gory zombie story becomes a silly, spooky one) or refuse with three safe alternatives.", "The policy lives in one reviewable file and is evaluated on a red-team set; the free tier allows only a few calls per minute, so it falls back to a sibling model."],
  ["4 · Output checks", "Before anything is voiced, the Editor re-scans every generated line and picture description for the chosen audience and measures the reading level. An unsafe draft is rewritten once with notes; anything still unsafe is removed line by line. Wishes you speak go through the same checks.", "Rules are cheap and certain but literal — which is why they sit behind a policy model, not instead of one."],
];

const DECISIONS = [
  ["The whole story in one call", "The Storyteller writes everything at once — cast, opening, the adventure, the choice and both endings — on the fastest free model (~2–4 s). Once narration starts, nothing is generated while you listen, so there are no pauses, and a story costs about two model calls instead of a dozen.", "Less moment-to-moment improvisation — so a spoken wish rewrites the story from the next sentence on (the rest of the part, the choice and both endings) while it keeps playing."],
  ["Safety in parallel, released at a gate", "The Guardian screens the request while the Storyteller writes, so safety adds no waiting — but nothing is spoken until it approves. A softened request is retold from the safe version.", "On a refusal the Storyteller's call is wasted."],
  ["Both endings written up front", "A choice continues instantly because both paths already exist. Only the chosen path's picture is painted; the other card shows an instant painted preview.", "About a third more words per story."],
  ["Short by design: 1, 2 or 3 minutes", "A demo must work every time on free tiers. Short stories with one picture per minute keep every story inside the limits — the planner scales words and pictures with the time you have, and every length, even one minute, has a choice.", "No epics in this prototype; the architecture itself is length-independent."],
  ["Story Spine × Freytag × Propp", "My earlier research (Kahaani) structured stories with Freytag's pyramid and Propp's functions. StoryWeaver adds the Story Spine (“because of that…”) for cause and effect, a planted detail that pays off, and a warm ending.", "Less freedom per story — in exchange for stories a child can follow."],
  ["Classic, measurable simplicity", "Stories open with “Once upon a time…”, introduce world and hero first, and are written to a reading level per audience, which the Editor measures.", "Readability formulas are a proxy."],
  ["A bookshelf for the busiest moments", "If no model can write the story within 12 seconds — free daily limits exhausted — StoryWeaver tells one of its own hand-written stories for that audience, with a choice and both endings, and says so. The Guardian's policy model has a budget too; past it, the lexicon decides.", "The listener may hear a story other than the one asked for — but never an error."],
  ["Fastest model first, with fallbacks", "Every agent role has an ordered chain of free models with separate limits; a rate-limited model is remembered and skipped until it recovers, so a busy model never stalls the story.", "Quality can vary slightly with the model that answered — visible in the crew panel."],
  ["Pictures that never stall", "Each picture is painted by the best model that can finish before it is shown (FLUX.2 when there is time, FLUX.1 schnell when it's urgent); when the free picture allowances are spent, a matching backdrop from the app's own picture shelf appears instantly (and the browser can still paint a paper-cut scene).", "Fewer pictures than a picture book; shelf backdrops show the place, not the characters."],
  ["Voices that never make you wait", "Auto uses your browser's own neural voices where they exist (instant), otherwise Microsoft neural voices from the server. Because the whole story is written up front, every sentence is voiced in parallel, in story order, before it is needed — and any line not ready within 2.5 s is spoken by your device instead.", "The same story can sound slightly different on different devices."],
  ["Procedural music and sound", "The score and every sound are synthesised live in the browser: no licences, endless variation, and the story controls them directly (mood, tension, ambience, effects).", "Stylised rather than recorded."],
];

export function diagram() {
  const box = (x, y, w, h, title, sub = "", tone = "gold") => {
    const stroke = { gold: "#f7c873", violet: "#a184ff", teal: "#62e3d2", rose: "#ff8fb3", sky: "#82c8ff" }[tone];
    return `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" fill="rgba(255,255,255,.05)" stroke="${stroke}" stroke-opacity=".7"/>
      <text x="${x + w / 2}" y="${y + (sub ? h / 2 - 3 : h / 2 + 5)}" text-anchor="middle" fill="#f5f2ff" font-size="13.5" font-weight="600">${esc(title)}</text>
      ${sub ? `<text x="${x + w / 2}" y="${y + h / 2 + 14}" text-anchor="middle" fill="#a9a3cc" font-size="11">${esc(sub)}</text>` : ""}</g>`;
  };
  const arrow = (d, dashed = false, color = "#8f88b6") =>
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" ${dashed ? 'stroke-dasharray="5 5"' : ""} marker-end="url(#ah)"/>`;
  const label = (x, y, text, color = "#a9a3cc", anchor = "middle") =>
    `<text x="${x}" y="${y}" text-anchor="${anchor}" fill="${color}" font-size="11">${esc(text)}</text>`;
  return `<svg viewBox="0 0 1000 440" role="img" aria-label="StoryWeaver pipeline">
    <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#8f88b6"/></marker></defs>
    <text x="16" y="24" fill="#f7c873" font-size="12" font-weight="700" letter-spacing="2">STORY GRAPH · ONE REQUEST, ABOUT TWO MODEL CALLS</text>
    ${box(16, 80, 130, 52, "Your request", "idea · who · length")}
    ${box(168, 80, 112, 52, "Lexicon", "instant precheck", "teal")}
    ${box(304, 44, 196, 52, "Guardian", "classifier + policy model", "teal")}
    ${box(304, 116, 196, 52, "Storyteller", "the whole story, ~2-4 s", "violet")}
    ${box(526, 80, 128, 52, "Gate", "allow/soften/refuse", "teal")}
    ${box(678, 80, 136, 52, "Editor", "every line, no model", "teal")}
    ${box(838, 80, 146, 52, "Release", "cast · voices · story", "gold")}
    ${arrow("M146 106 H166")}
    ${arrow("M280 100 C292 100 292 70 302 70")}${arrow("M280 112 C292 112 292 142 302 142")}
    ${arrow("M500 70 C514 70 514 100 524 100")}${arrow("M500 142 C514 142 514 112 524 112")}
    ${arrow("M654 106 H676")}${arrow("M814 106 H836")}
    ${label(402, 186, "in parallel: safety adds no wait")}
    ${label(530, 152, "soften → retold from the safe version", "#ff8fb3", "start")}
    <text x="230" y="244" fill="#f7c873" font-size="12" font-weight="700" letter-spacing="2">WHILE YOU LISTEN · NOTHING IS GENERATED UNLESS YOU SPEAK</text>
    ${box(16, 268, 180, 56, "Director", "plays the written story", "rose")}
    ${box(230, 262, 176, 40, "Narrator", "neural voices", "gold")}
    ${box(230, 312, 176, 40, "Illustrator", "1 picture per minute", "gold")}
    ${box(230, 362, 176, 40, "Composer · Sound", "procedural, live", "gold")}
    ${box(440, 296, 150, 56, "You", "listen · look · speak", "rose")}
    ${box(626, 262, 160, 40, "Choice", "both endings ready", "teal")}
    ${box(626, 312, 160, 40, "Question", "1 small call", "sky")}
    ${box(626, 362, 160, 40, "Wish", "rewritten from the next line", "violet")}
    ${box(820, 312, 164, 40, "Story continues", "never pauses", "gold")}
    ${arrow("M911 132 V200 Q911 212 899 212 H118 Q106 212 106 224 V266")}
    ${arrow("M196 290 C212 290 212 282 228 282")}${arrow("M196 296 C212 296 212 332 228 332")}${arrow("M196 302 C212 302 212 382 228 382")}
    ${arrow("M406 282 C424 282 424 318 438 318")}${arrow("M406 332 H438")}${arrow("M406 382 C424 382 424 340 438 340")}
    ${arrow("M590 316 C608 316 608 282 624 282")}${arrow("M590 324 H624")}${arrow("M590 332 C608 332 608 382 624 382")}
    ${arrow("M786 282 C804 282 804 324 818 328")}${arrow("M786 332 H818")}${arrow("M786 382 C804 382 804 340 818 336")}
    ${label(500, 428, "the host answers a wish at once; the story continues with it from the next sentence — never a pause", "#62e3d2")}
  </svg>`;
}

const KIND = { agent: "LLM agent", safety: "Safety", code: "Plain code", media: "Performer" };

/** Meet the crew, on a stage: the curtains part, and each member steps into the spotlight in turn — then the whole
 *  line-up takes a bow. Starts when the stage scrolls into view; anyone can be called back with a tap. */
function theatre() {
  const root = $("#hiw-crew");
  root.innerHTML = `<div class="th-valance"></div>
    <div class="th-stage"><div class="th-spot"></div><div class="th-pool"></div>
      <div class="th-feature" id="th-feature" aria-live="polite"></div>
      <div class="th-lineup">${CREW.map((c, i) => `<button class="th-actor" data-i="${i}" style="--i:${i}"><span class="ai">${c.icon}</span>${esc(c.name)}</button>`).join("")}</div>
    </div>
    <div class="th-curtain l"></div><div class="th-curtain r"></div>
    <button class="th-replay" type="button">↺ Raise the curtain again</button>`;
  const actors = [...root.querySelectorAll(".th-actor")];
  let timers = [];
  const feature = (i, kicker = "Now introducing") => {
    const c = CREW[i];
    const box = $("#th-feature");
    box.classList.remove("swap");
    void box.offsetWidth; // restart the entrance
    box.innerHTML = `<div class="th-kicker">${esc(kicker)}</div><div class="th-ico">${c.icon}</div><h4>${esc(c.name)}</h4>
      <div class="th-tags"><span>${esc(KIND[c.kind] || c.kind)}</span><span>${esc(c.model)}</span></div><p>${esc(c.role)}</p>`;
    box.classList.add("swap");
    actors.forEach((a, k) => a.classList.toggle("lit", k === i));
  };
  const show = () => {
    timers.forEach(clearTimeout);
    timers = [];
    root.classList.remove("bow");
    root.classList.add("open");
    CREW.forEach((_, i) => timers.push(setTimeout(() => { actors[i].classList.add("on"); feature(i); }, 1300 + i * 1700)));
    timers.push(setTimeout(() => { root.classList.add("bow"); feature(1, "Curtain call — the lead"); }, 1300 + CREW.length * 1700));
  };
  const reset = () => {
    timers.forEach(clearTimeout);
    root.classList.remove("open", "bow");
    actors.forEach((a) => a.classList.remove("on", "lit"));
    $("#th-feature").innerHTML = "";
  };
  actors.forEach((a) => a.addEventListener("click", () => {
    timers.forEach(clearTimeout);
    actors.forEach((x) => x.classList.add("on"));
    feature(Number(a.dataset.i), "In the spotlight");
  }));
  root.querySelector(".th-replay").addEventListener("click", () => { reset(); setTimeout(show, 900); });
  new IntersectionObserver((entries, observer) => {
    if (entries.some((e) => e.isIntersecting)) { observer.disconnect(); show(); }
  }, { threshold: 0.35 }).observe(root);
}

export async function renderHowItWorks() {
  theatre();
  $("#hiw-diagram").innerHTML = diagram();
  $("#hiw-safety").innerHTML = SAFETY.map(([t, p, tr]) => `<div class="decision"><b>${esc(t)}</b><p>${esc(p)}</p><div class="tradeoff">${esc(tr)}</div></div>`).join("");
  $("#hiw-decisions").innerHTML = DECISIONS.map(([t, p, tr]) => `<div class="decision"><b>${esc(t)}</b><p>${esc(p)}</p><div class="tradeoff">${esc(tr)}</div></div>`).join("");
  let metrics = [["—", "Run eval/run_eval.py to fill these numbers in."]];
  try {
    const data = await getJSON("/data/eval.json");
    metrics = data.highlights || metrics;
  } catch { /* no evaluation results bundled */ }
  $("#hiw-metrics").innerHTML = metrics.map(([v, l]) => `<div class="metric"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
}
