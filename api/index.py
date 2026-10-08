"""Vercel entry point: exposes the FastAPI app as a Python serverless function (static files come from public/).

Vercel hands the function the rewrite's destination (``/api/index``) rather than the path that was requested, so
``vercel.json`` passes the requested route along as ``?__route=…`` and this wrapper restores it before FastAPI routes
the request. Locally (``uv run storyweaver``) the app is served directly and none of this applies.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storyweaver.server import app as fastapi_app


async def app(scope, receive, send):
    if scope["type"] == "http" and scope.get("path") == "/api/index":
        query = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
        route = next((value for key, value in query if key == "__route"), None)
        if route is not None:
            path = f"/api/{route.lstrip('/')}"
            rest = urlencode([(key, value) for key, value in query if key != "__route"]).encode()
            scope = {**scope, "path": path, "raw_path": path.encode(), "query_string": rest}
    return await fastapi_app(scope, receive, send)
