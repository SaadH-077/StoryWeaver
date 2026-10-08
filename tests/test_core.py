"""Deterministic building blocks: lexicon, planner, readability, schemas, router and picture planning."""

import time

import httpx
import pytest

from storyweaver import llm, readability
from storyweaver.agents.interpreter import as_wish
from storyweaver.agents.storyteller import ask_aloud, options_in
from storyweaver.llm import LLMRouter, describe_error, extract_json, retry_after
from storyweaver.media import picture_shelf
from storyweaver.media.images import ImageError, ImageService
from storyweaver.planner import shape_for
from storyweaver.safety import lexicon
from storyweaver.schemas import ChapterScript, EditorReview, ScriptLine, StoryRemainder, StoryRequest


@pytest.mark.parametrize("text", ["how to make a bomb", "a story with s e x scenes", "a st0ry ab0ut p0rn",
                                  "a story telling kids to hurt themselves", "the hero drinks bleach"])
def test_lexicon_blocks_clear_harm(text):
    assert lexicon.worst(lexicon.scan(text)) == "block"


@pytest.mark.parametrize("text", ["A Maine Coon cat detective", "A bomb-sniffing dog at the airport",
                                  "A little hedgehog who is afraid of the dark", "She wants to shoot the winning goal"])
def test_lexicon_lets_harmless_stories_through(text):
    assert lexicon.worst(lexicon.scan(text)) != "block"


def test_personal_data_is_redacted_but_dates_are_not():
    assert "0151" not in lexicon.redact_personal_data("call me on 0151 2345 6789")
    assert "2026" in lexicon.redact_personal_data("on 12.05.2026 we went out")


@pytest.mark.parametrize("minutes", [1, 2, 3])
def test_planner_fits_the_minutes_with_one_picture_per_minute(minutes):
    shape = shape_for(minutes)
    # targets sit ~20-25% above the nominal length: the fast model reliably writes a little short (measured)
    assert minutes <= shape.total_words / 150 <= minutes * 1.3
    assert shape.pictures == minutes  # a fixed picture budget that fits the free tiers
    assert shape.chapters not in shape.choice_after  # the last chapter never asks
    assert shape.choice_after == [1]  # every story, even a one-minute tale, has a moment to decide


def test_a_wish_names_who_joins_the_story_with_a_clean_emoji():
    part = {"title": "t", "summary": "s", "lines": ["One.", "Two.", "Three."]}
    out = StoryRemainder.model_validate({"parts": [part], "new_characters": [
        {"name": "Flick", "emoji": "firefly 🪲!", "description": "a friendly firefly"}, {"emoji": "🦉"}, "Owl"]})
    assert [(c.name, c.emoji) for c in out.new_characters] == [("Flick", "🪲")]


@pytest.mark.parametrize(("question", "options"), [
    ("Should Pip follow the little light, or wake up Mo?", ["Follow the little light", "Wake up Mo"]),
    ("What should Elsa do: open the door, or knock first?", ["Open the door", "Knock first"]),
    ("What should happen next?", []),
])
def test_the_options_a_spoken_question_names(question, options):
    assert options_in(question) == options


def test_the_spoken_question_always_names_the_options_on_the_cards():
    script = ChapterScript.model_validate({"title": "t", "summary": "s", "lines": [
        "Pip met Flick.", "Flick glowed.", "It was dark.", "Should Pip go outside? Or hide under his bed?"],
        "choices": [{"keyword": "light", "label": "Turn on the light"},
                    {"keyword": "opal", "label": "Listen to Opal"}]})
    asked = ask_aloud(script, "Pip")
    assert asked == "What should Pip do: turn on the light, or listen to Opal?" == script.lines[-1].text
    assert len(script.lines) == 4  # the mismatched question was replaced, not added to
    assert ask_aloud(script, "Pip") == asked and len(script.lines) == 4  # a matching question is kept as it is


def test_readability_orders_simple_before_complex():
    simple = "Pip is a hedgehog. He likes the sun. He is shy."
    hard = "Notwithstanding considerable apprehension, the hedgehog contemplated nocturnal circumstances."
    assert readability.grade(simple) < readability.grade(hard)


def test_script_line_keeps_inner_quotes_balanced():
    assert ScriptLine(text='"Hello there!"').text == "Hello there!"
    assert ScriptLine(text='She said, "Come with me."').text == 'She said, "Come with me."'


def test_story_request_validates_minutes_and_names():
    assert StoryRequest(prompt="a fox", minutes=3).minutes == 3
    with pytest.raises(ValueError):
        StoryRequest(prompt="a fox", minutes=5)


def test_router_helpers():
    assert extract_json('Sure! ```json\n{"a": 1}\n```') == {"a": 1}
    assert retry_after(RuntimeError("Please try again in 7.5s")) == pytest.approx(7.5)
    assert describe_error(RuntimeError("Error code: 429 rate limit")) == "rate-limited"


class FlakyRouter(LLMRouter):
    def __init__(self, settings, outcomes):
        super().__init__(settings)
        self.outcomes, self.attempts = outcomes, []

    async def _structured_once(self, provider, model, schema, messages, temperature, max_tokens):
        self.attempts.append(model)
        outcome = self.outcomes[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return schema.model_validate(outcome), (1, 1)


async def test_router_remembers_rate_limits(settings):
    settings.route_editor = "groq:a,groq:b"
    ok = {"approved": True}
    router = FlakyRouter(settings, {"a": [RuntimeError("429 rate limit, try again in 30s")], "b": [ok, ok]})
    await router.structured("editor", EditorReview, [("human", "x")])
    await router.structured("editor", EditorReview, [("human", "x")])
    assert router.attempts == ["a", "b", "b"]  # the second call skips the model that is cooling down


async def test_router_waits_for_the_preferred_model_when_there_is_time(settings, monkeypatch):
    settings.route_editor = "groq:a,groq:b"
    router = FlakyRouter(settings, {"a": [RuntimeError("429, try again in 0.05s"), {"approved": True}],
                                    "b": [{"approved": False}]})
    review, info = await router.structured("editor", EditorReview, [("human", "x")], patience=5)
    assert info.model == "a" and review.approved


def test_route_skips_providers_without_keys(settings):
    settings.route_editor = "groq:a,gemini:b,groq:c"
    assert settings.route("editor") == [("groq", "a"), ("groq", "c")]
    assert llm.ROLE_TIMEOUT_S["storyteller"] < llm.ROLE_TIMEOUT_S["writer"]


def test_pictures_use_flux2_only_when_it_is_fast_enough(settings):
    settings.cloudflare_api_token, settings.cloudflare_account_id = "t", "a"
    images = ImageService(settings)
    assert images.plan(None)[0] == "klein"
    assert images.plan(0)[0] == "schnell"  # needed now: the fast model first
    images.expected["klein"] = 40
    assert images.plan(20) == ["schnell", "pollinations", "klein"]


def test_a_spent_daily_picture_allowance_is_skipped_until_it_resets(settings):
    settings.cloudflare_api_token, settings.cloudflare_account_id = "t", "a"
    images = ImageService(settings)
    spent = httpx.Response(429, json={"errors": [{"code": 4006, "message": "you have used up your daily free "
                                                  "allocation of 10,000 neurons"}]},
                           request=httpx.Request("POST", "https://api.cloudflare.com"))
    with pytest.raises(ImageError):
        images._check_cloud(spent)
    assert images.plan(0) == ["pollinations"]  # no picture waits on a request that can only fail


def test_the_picture_shelf_matches_the_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(picture_shelf, "FOLDER", tmp_path)
    assert picture_shelf.pick("A hedgehog in the forest") is None  # not painted yet: the browser paints instead
    for backdrop in picture_shelf.SHELF:
        backdrop.path.write_bytes(b"jpeg")
    assert picture_shelf.pick("Pip walks between the tall trees of the forest").id == "forest"
    assert picture_shelf.pick("Pip under the moon among the forest trees at night").id == "forest_night"
    assert picture_shelf.pick("A dragon takes a tray of warm bread out of the oven").id == "bakery"
    assert picture_shelf.pick("Something nobody could describe").id == picture_shelf.DEFAULT


async def test_when_every_painter_is_out_the_shelf_answers_at_once(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(picture_shelf, "FOLDER", tmp_path)
    (tmp_path / "castle.jpg").write_bytes(b"jpeg:castle")
    images = ImageService(settings)  # no Cloudflare keys in the test settings
    images._paused_until = time.monotonic() + 60  # and Pollinations has just said "too many"
    picture = await images.generate("A castle on a hill", 768, 512, deadline=0, shelf="The queen's castle")
    assert picture.provider == "shelf:castle" and picture.data.endswith(b"castle")
    with pytest.raises(ImageError):  # a portrait has no stand-in
        await images.generate("Portrait of the queen", 512, 512, deadline=0)


def test_contact_details_never_reach_a_model():
    text = lexicon.redact_personal_data("A story for Mia at 12 Baker Street, mia@example.com, +49 177 1234567")
    assert text == "A story for Mia at [removed], [removed], [removed]"


@pytest.mark.parametrize(("said", "wish"), [
    ("Please add a friendly firefly who glows!", "Add a friendly firefly who glows"),
    ("make the owl sing a song", "Make the owl sing a song"),
    ("Ooh, can you bring a dragon", "Can you bring a dragon"),
    ("I want a rainbow", "I want a rainbow"),
])
def test_a_plain_wish_needs_no_model(said, wish):
    assert as_wish(said) == wish


@pytest.mark.parametrize("said", ["Why is the moon sad?", "What colour is the lantern", "Can the owl tell a joke?",
                                  "the second one"])
def test_questions_and_choices_are_not_taken_for_wishes(said):
    assert as_wish(said) is None
