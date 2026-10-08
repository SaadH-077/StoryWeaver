"""Vercel entry point: exposes the FastAPI app as a Python serverless function (static files come from public/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storyweaver.server import app as _app  # noqa: E402


async def app(scope, receive, send):  # temporary: report the path the function receives
    if scope["type"] != "http":
        return await _app(scope, receive, send)
    seen = f"{scope.get('path', '')}|root={scope.get('root_path', '')}|raw={scope.get('raw_path', b'').decode(errors='replace')}"

    async def tagged(message):
        if message["type"] == "http.response.start":
            message["headers"] = [*message.get("headers", []), (b"x-seen-path", seen.encode())]
        await send(message)

    return await _app(scope, receive, tagged)
