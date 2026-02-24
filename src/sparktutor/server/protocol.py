"""JSON-lines protocol messages for VS Code bridge communication."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Request:
    """Incoming request from the VS Code extension."""
    id: int
    method: str
    params: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> Request:
        return cls(
            id=data["id"],
            method=data["method"],
            params=data.get("params", {}),
        )


@dataclass
class Response:
    """Outgoing response to the VS Code extension."""
    id: int
    result: Optional[dict] = None
    error: Optional[str] = None

    def to_json_line(self) -> str:
        d = {"id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return json.dumps(d) + "\n"


@dataclass
class Notification:
    """Server-initiated message (no id, no response expected)."""
    method: str
    params: dict = field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps({"method": self.method, "params": self.params}) + "\n"
