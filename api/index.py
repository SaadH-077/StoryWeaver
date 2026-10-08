"""Vercel entry point: exposes the FastAPI app as a Python serverless function (static files come from public/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storyweaver.server import app  # noqa: F401
