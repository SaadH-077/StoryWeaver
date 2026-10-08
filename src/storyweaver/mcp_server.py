"""StoryWeaver as an MCP server (Model Context Protocol, stdio transport).

Any MCP-capable assistant (Claude Desktop, an IDE agent, a voice assistant…) can discover and call StoryWeaver's
capabilities as tools:

* ``tell_story``   — the full story graph (Guardian ‖ Storyteller → gate → Editor → release), text only;
* ``check_safety`` — the multi-layer safety screen on any story request.

Run:  uv run storyweaver-mcp
"""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer

from .config import get_settings
from .headless import run_story
from .llm import LLMRouter
from .safety.guardian import screen_request
from .schemas import StoryRequest

server = MCPServer(
    name="storyweaver",
    title="StoryWeaver storyteller",
    instructions=("StoryWeaver writes safe, well-structured stories on any topic for children, families or adults. "
                  "Use tell_story to have its agent crew write a complete story, and check_safety to see how its "
                  "safety layers judge a request."),
)


@server.tool(description="Write a complete story with StoryWeaver's agent crew: the Guardian screens the request "
                         "while the Storyteller writes the whole story on a Story-Spine arc, then the Editor checks "
                         "every line for the audience. The listener's choice is taken automatically (first option). "
                         "Returns the story as text.")
async def tell_story(prompt: str, audience: Literal["kids", "family", "adults"] = "family",
                     minutes: Literal[1, 2, 3] = 2, hero_name: str = "") -> str:
    request = StoryRequest(prompt=prompt, audience=audience, minutes=minutes, hero_name=hero_name or None)
    result = await run_story(request, get_settings())
    if result["refused"]:
        verdict = result["screening"].verdict
        return f"StoryWeaver declined this request ({verdict.reason}). Safe ideas: {'; '.join(verdict.alternatives)}"
    bible = result["bible"]
    parts = [f"# {bible.title}", f"_{bible.logline}_", "", bible.opening, ""]
    for number, chapter in enumerate(result["chapters"], start=1):
        parts.append(f"## {number}. {bible.chapters[number - 1].title}")
        for line in chapter.lines:
            character = bible.character(line.speaker)
            parts.append(line.text if line.speaker == "narrator" else
                         f"{character.name if character else line.speaker}: “{line.text}”")
        if chapter.choices:
            parts.append(f"(Choice: {' / '.join(c.label for c in chapter.choices)} — the first was taken.)")
        parts.append("")
    return "\n".join(parts)


@server.tool(description="Screen a story request with StoryWeaver's safety layers (lexicon, prompt-injection "
                         "classifier, policy model). Returns the decision and each layer's verdict.")
async def check_safety(prompt: str, audience: Literal["kids", "family", "adults"] = "family") -> str:
    screening = await screen_request(LLMRouter(get_settings()), StoryRequest(prompt=prompt, audience=audience))
    layers = "\n".join(f"- {layer.layer}: {layer.verdict} {layer.detail}".rstrip() for layer in screening.layers)
    verdict = screening.verdict
    return f"Decision: {verdict.decision} ({verdict.reason})\n{layers}"


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
