"""StoryWeaver's layered safety system.

1. ``lexicon``  — deterministic patterns for clearly harmful text (instant, cannot be argued with)
2. ``guardian`` — a prompt-injection classifier + a policy model applying a written content policy
3. output checks — every generated line and image prompt is re-scanned; an Editor model reviews each chapter
"""
