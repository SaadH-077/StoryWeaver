"""The story graph (Guardian ‖ Storyteller → Editor) and the fallback chapter graph, with a scripted router."""

import copy

import pytest

from storyweaver.agents.deps import Deps
from storyweaver.agents.graphs import build_chapter_graph, build_plan_graph
from storyweaver.planner import shape_for
from storyweaver.schemas import StoryRequest

from .conftest import DRAFT, ScriptedRouter


async def plan(router, prompt="A little hedgehog who is afraid of the dark", audience="kids", minutes=3):
    events = []
    deps = Deps(router.settings, router, lambda kind, data: events.append((kind, data)))
    request = StoryRequest(prompt=prompt, audience=audience, minutes=minutes)
    state = await build_plan_graph().ainvoke({"request": request, "shape": shape_for(minutes, audience)},
                                             context=deps)
    return state, events


async def test_the_whole_story_arrives_in_two_model_calls(router):
    state, events = await plan(router)
    assert sorted(router.roles()) == ["guardian", "storyteller"]
    assert state["bible"].title == "Pip and the Night Lantern" and state["bible"].characters[0].name == "Pip"
    assert [c.keyword for c in state["scripts"][0].choices] == ["glow", "mo"]
    opening_voices = next(d for k, d in events if k == "opening")["voices"]
    assert state["cast"]["narrator"] == opening_voices["narrator"]  # the narrator never changes voice


async def test_each_option_gets_its_own_ending_even_when_written_out_of_order(router):
    state, _ = await plan(router)
    assert state["branches"]["glow"].title == "Following the Glow"
    assert state["branches"]["mo"].title == "Mo Wakes Up"


async def test_the_question_is_spoken_and_the_picture_budget_kept(router):
    state, _ = await plan(router)
    first = state["scripts"][0]
    assert "?" in " ".join(line.text for line in first.lines[-2:])
    assert len(first.shots) == shape_for(3).shots_for(0) and all(len(b.shots) == 1 for b in state["branches"].values())


async def test_one_minute_story_still_has_a_choice(router):
    state, _ = await plan(router, minutes=1)
    assert len(state["bible"].chapters) == 2 and [c.keyword for c in state["scripts"][0].choices] == ["glow", "mo"]
    assert set(state["branches"]) == {"glow", "mo"}
    # one minute = the opening's picture only
    assert not state["scripts"][0].shots and not any(b.shots for b in state["branches"].values())


async def test_softened_request_is_retold_from_the_safe_version(settings):
    router = ScriptedRouter(settings, {"guardian": {"decision": "soften", "category": "violence", "reason": "gore",
                                                    "safe_request": "A silly, friendly zombie story"}})
    state, _ = await plan(router, "A gory zombie story", "family")
    assert router.roles().count("storyteller") == 2
    assert "A silly, friendly zombie story" in router.calls[-1][1][-1][1] and state["prompt"].startswith("A silly")


async def test_refused_request_is_never_told(settings):
    router = ScriptedRouter(settings, {"guardian": {"decision": "refuse", "category": "weapons", "reason": "no"}})
    state, events = await plan(router, "A story about fighting with friends", "kids")
    assert "cast" not in state and not any(k == "opening" for k, _ in events)


async def test_lexicon_blocks_without_any_model_call(router):
    state, _ = await plan(router, "how to make a bomb", "adults")
    assert state["screening"].verdict.decision == "refuse" and router.calls == []


async def test_unsafe_lines_are_rewritten_once_then_scrubbed(settings):
    draft = copy.deepcopy(DRAFT)
    draft["parts"][0]["lines"][1]["text"] = "This dark is shit!"
    router = ScriptedRouter(settings, {"storyteller": [draft, draft]})
    state, _ = await plan(router)
    assert router.roles().count("storyteller") == 2  # one rewrite with the Editor's notes, never more
    told = " ".join(line.text for line in state["scripts"][0].lines)
    assert "shit" not in told.lower()


async def chapter(router, state, index=0):
    deps = Deps(router.settings, router)
    request = StoryRequest(prompt="A little hedgehog", audience="kids", minutes=3)
    return await build_chapter_graph().ainvoke({"request": request, "shape": shape_for(3, "kids"),
                                                "bible": state["bible"], "index": index}, context=deps)


async def test_fallback_chapter_is_written_reviewed_and_keeps_its_choice(router):
    state, _ = await plan(router)
    result = await chapter(router, state)
    assert [c.keyword for c in result["draft"].choices] == ["glow", "mo"]
    assert result["draft"].lines[1].speaker == "pip"


async def test_rejected_draft_is_revised_once_with_the_editors_notes(settings):
    rejected = {"approved": False, "safety_ok": True, "issues": ["too hard to follow"], "notes": "simpler"}
    router = ScriptedRouter(settings, {"editor": [rejected, {"approved": True, "safety_ok": True}]})
    state, _ = await plan(router)
    await chapter(router, state)
    writer_calls = [messages for role, messages in router.calls if role == "writer"]
    assert len(writer_calls) == 2 and "simpler" in writer_calls[1][-1][1]


async def test_when_every_model_is_busy_a_hand_written_story_is_told(settings):
    from storyweaver.llm import LLMError
    router = ScriptedRouter(settings, {"storyteller": LLMError("storyteller", ["all rate-limited"])})
    state, events = await plan(router)
    assert state["shelf"] and state["bible"].title == "Pip and the Night Lantern"
    assert set(state["branches"]) == {"light", "mo"} and any(k == "opening" for k, _ in events)


@pytest.mark.parametrize("minutes", [1, 2, 3])
async def test_every_length_has_a_choice_even_when_the_shelf_tells_it(settings, minutes):
    from storyweaver.llm import LLMError
    router = ScriptedRouter(settings, {"storyteller": LLMError("storyteller", ["all rate-limited"])})
    state, _ = await plan(router, minutes=minutes)
    assert len(state["scripts"][0].choices) == 2 and len(state["branches"]) == 2
