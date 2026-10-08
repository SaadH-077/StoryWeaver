"""Entry point: ``uv run storyweaver`` or ``python -m storyweaver``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
import threading
import webbrowser


def main() -> int:
    parser = argparse.ArgumentParser(prog="storyweaver", description="Run the StoryWeaver server.")
    parser.add_argument("--host", help="interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpcore", "google_genai", "urllib3", "phonemizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    import uvicorn

    from .config import get_settings

    settings = get_settings()
    if not settings.groq_api_key:
        print("\n  GROQ_API_KEY is missing. Copy .env.example to .env and add your free key from "
              "https://console.groq.com/keys\n", file=sys.stderr)
        return 1
    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    with socket.socket() as probe:  # two servers on one port would answer requests with different code, at random
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, port)) == 0:
            print(f"\n  Something is already running at {url} — probably an older StoryWeaver.\n"
                  "  Close that window (or press Ctrl+C there) and start this one again, or use --port 8001.\n",
                  file=sys.stderr)
            return 1
    print(f"\n  StoryWeaver is running at {url}\n")
    if not args.no_browser:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    loop = "auto"
    if sys.platform == "win32":
        # Windows' default (proactor) event loop stops accepting connections for good after a client aborts a request
        # mid-flight ("WinError 64") — exactly what happens when a listener leaves one story for the next. The selector
        # loop has no such failure.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = "none"
    uvicorn.run("storyweaver.server:app", host=host, port=port, log_level="warning", loop=loop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
