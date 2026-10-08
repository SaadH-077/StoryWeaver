// The StoryWeaver crew — shared by the weaving overlay, the crew drawer and the "How it works" page.
// Only two of them call a language model per story (Guardian and Storyteller); the rest are code, the browser,
// or are called only when you speak.
export const CREW = [
  { id: "guardian", icon: "🛡️", name: "Guardian", model: "Prompt Guard 2 · gpt-oss-safeguard", kind: "safety",
    role: "Screens every request in layers: a deterministic lexicon, a prompt-injection classifier and a policy model with a written content policy." },
  { id: "storyteller", icon: "🕯️", name: "Storyteller", model: "gpt-oss-20b (fastest)", kind: "agent",
    role: "Writes the whole story in one pass, in parallel with the Guardian: cast, “Once upon a time…”, the adventure on the Story Spine, the choice and both endings — so nothing waits once it starts." },
  { id: "editor", icon: "🔍", name: "Editor", model: "rules (no model call)", kind: "safety",
    role: "Checks every line and picture description for the audience — safety lexicon and reading level; an unsafe draft is rewritten once, then scrubbed line by line." },
  { id: "casting", icon: "🎭", name: "Casting Director", model: "code", kind: "code",
    role: "Gives the narrator and every character a distinct, fitting voice — deterministic, instant and testable." },
  { id: "illustrator", icon: "🎨", name: "Illustrator", model: "FLUX.2 klein · FLUX.1 schnell", kind: "media",
    role: "Paints one picture per minute of story at its most striking moments, picking the best model that can finish in time; paints a storybook scene in the browser if none can." },
  { id: "composer", icon: "🎼", name: "Composer", model: "procedural (Web Audio)", kind: "media",
    role: "Scores the story live: a theme for this story, harmony and tempo per part, swelling with the tension." },
  { id: "sound", icon: "🌧️", name: "Sound Designer", model: "procedural (Web Audio)", kind: "media",
    role: "Builds the world's soundscape — rain, forest, city, space… — and plays the effects the script asks for." },
  { id: "narrator", icon: "🎙️", name: "Narrator", model: "neural voices", kind: "media",
    role: "Speaks every line in the cast voices, using the fastest good voice engine measured on your device." },
  { id: "director", icon: "🎬", name: "Director", model: "your browser", kind: "code",
    role: "Runs the show: the whole story is in hand before it starts, so it plays without a pause; a choice continues at once." },
  { id: "ear", icon: "👂", name: "Listener's Ear", model: "Whisper + gpt-oss-120b", kind: "agent",
    role: "Understands what you say: a choice (no model needed), a question the narrator answers, or a wish — the story is rewritten from the next sentence on." },
];

export const PLAN_CREW = ["guardian", "storyteller", "editor", "casting"];
export const crewById = Object.fromEntries(CREW.map((c) => [c.id, c]));
