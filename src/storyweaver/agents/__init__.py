"""The StoryWeaver crew. Each module is one role; ``graphs.py`` wires them into two LangGraph workflows:

* the **plan graph**   — Guardian ∥ Lore Scout ∥ Story Architect → gate → Casting (one request per story)
* the **chapter graph** — Writer → safety & readability checks → Editor ⇄ (one revision) → finalise
"""
