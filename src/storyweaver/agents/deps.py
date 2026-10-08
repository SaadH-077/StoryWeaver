"""Runtime dependencies handed to every graph node (LangGraph ``context_schema``).

Graphs are stateless per request: everything a node needs either arrives in the request (the story so far
travels with the listener's browser) or is a service injected here. Tests inject fakes through the same object.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..llm import CallInfo, LLMRouter


def _ignore(kind: str, data: dict[str, Any]) -> None:
    return None


@dataclass
class Deps:
    settings: Settings
    router: LLMRouter
    emit: Callable[[str, dict[str, Any]], None] = _ignore

    # LLM router observer interface
    def trace(self, info: CallInfo) -> None:
        self.emit("llm", info.as_event())

    def waiting(self, role: str, seconds: float, planned: bool = False) -> None:
        if planned:  # a lookahead call waiting for its preferred model — nobody is waiting for it yet
            self.emit("agent", {"agent": role, "state": "queued",
                                "detail": f"waiting {seconds:.0f} s for the preferred model (free-tier limit)"})
        else:
            self.emit("agent", {"agent": role, "state": "waiting",
                                "detail": f"free-tier limit reached — retrying in {seconds:.0f} s"})

    def agent(self, name: str, state: str, detail: str = "", **extra: Any) -> None:
        self.emit("agent", {"agent": name, "state": state, "detail": detail, **extra})
