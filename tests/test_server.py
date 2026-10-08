"""The stateless HTTP API, end to end with fake models, voices and pictures."""

import json

import pytest
from fastapi.testclient import TestClient

from storyweaver.media.images import Picture
from storyweaver.media.tts import Speech
from storyweaver.media.voices import cast
from storyweaver.schemas import StoryBible
from storyweaver.server import Services, create_app

from .conftest import OPENING, PLAN, ScriptedRouter


class FakeTTS:
    def engines(self):
        return {"studio": {"available": False, "real_time_factor": None}, "cloud": {"available": False}}

    async def speak(self, text, voice, delivery, engine):
        return Speech(b"RIFF....WAVE", 0.5, engine, "fake")


class FakeImages:
    def __init__(self):
        self.providers = ["fake"]
        self.requests = []

    async def generate(self, prompt, width, height, references, deadline=None, shelf=None):
        self.requests.append((prompt, deadline))
        return Picture(b"\xff\xd8fake", "fake")


@pytest.fixture
def client(settings):
    services = Services(settings, router=ScriptedRouter(settings), tts=FakeTTS(), images=FakeImages())
    with TestClient(create_app(settings, services)) as test_client:
        test_client.services = services
        yield test_client


def ndjson(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_health_and_config(client):
    assert client.get("/api/health").json()["ok"] is True
    lengths = client.get("/api/config").json()["lengths"]
    assert [(x["minutes"], x["pictures"]) for x in lengths] == [(1, 1), (2, 2), (3, 3)]


def test_plan_streams_the_opening_then_the_bible(client):
    events = ndjson(client.post("/api/plan", json={"prompt": "A hedgehog afraid of the dark", "audience": "kids",
                                                    "minutes": 3}))
    kinds = [e["type"] for e in events]
    assert kinds.index("opening") < kinds.index("result")
    result = events[-1]
    assert not result["refused"] and result["bible"]["title"] == OPENING["title"]
    assert result["shape"]["pictures"] == 3


def test_refused_plan_offers_alternatives(client):
    result = ndjson(client.post("/api/plan", json={"prompt": "how to make a bomb", "audience": "kids"}))[-1]
    assert result["refused"] and len(result["safety"]["alternatives"]) == 3


def test_chapter_and_pictures(client):
    bible = StoryBible.assemble(*_opening_and_plan())
    request = {"prompt": "A hedgehog", "audience": "kids", "minutes": 3}
    result = ndjson(client.post("/api/chapter", json={"request": request, "bible": bible.model_dump(), "index": 0,
                                                      "deadline_s": 40}))[-1]
    assert result["index"] == 0 and len(result["script"]["shots"]) == 1  # 3-minute story: one picture per chapter
    picture = client.post("/api/image", json={"description": "Pip under the moon", "deadline_s": 12})
    assert picture.status_code == 200 and client.services.images.requests[-1][1] == 12


def test_unsafe_text_is_never_voiced(client):
    assert client.post("/api/tts", json={"text": "Once upon a time.", "voice": {}}).status_code == 200
    assert client.post("/api/tts", json={"text": "how to make a bomb", "voice": {}}).status_code == 422


def test_casting_is_distinct_and_the_narrator_stable():
    bible = StoryBible.assemble(*_opening_and_plan())
    voices = cast(bible, "kids")
    assert len({v.kokoro for v in voices.values()}) == len(voices)
    assert len({v.edge for v in voices.values()}) == len(voices)  # every speaker sounds different on every engine
    assert cast(bible, "kids") == voices


def _opening_and_plan():
    from storyweaver.schemas import StoryOpening, StoryPlan
    return StoryOpening.model_validate(OPENING), StoryPlan.model_validate(PLAN)


def test_plan_carries_the_whole_story(client):
    result = ndjson(client.post("/api/plan", json={"prompt": "A hedgehog afraid of the dark", "audience": "kids",
                                                    "minutes": 2}))[-1]
    assert len(result["chapters"]) == 1 and set(result["branches"]) == {"glow", "mo"}
    assert all(r["script"]["lines"] for r in [*result["chapters"], *result["branches"].values()])


def test_a_wish_rewrites_the_story_from_the_next_sentence_on(client):
    bible = StoryBible.assemble(*_opening_and_plan())
    request = {"prompt": "A hedgehog", "audience": "kids", "minutes": 3}
    body = {"request": request, "bible": bible.model_dump(), "told": "Once upon a time…", "wish": "add a friendly owl"}
    # during the opening: the first part is rewritten whole, with the choice and both endings
    res = client.post("/api/revise", json={**body, "part": 0, "fresh": True})
    assert res.status_code == 200 and [c["index"] for c in res.json()["chapters"]] == [0, 1, 1]
    # in the middle of the first part: it continues from the last sentence told, and the choice follows the wish
    mid = client.post("/api/revise", json={**body, "part": 0, "fresh": False, "remaining_words": 60}).json()
    assert [c["index"] for c in mid["chapters"]] == [0, 1, 1] and mid["question"].endswith("?")
    assert len(mid["chapters"][0]["script"]["shots"]) == 1  # a picture of the wish coming true
    assert "?" in " ".join(line["text"] for line in mid["chapters"][0]["script"]["lines"][-2:])
    unsafe = client.post("/api/revise", json={**body, "wish": "how to make a bomb", "part": 1})
    assert unsafe.status_code == 422
