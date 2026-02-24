"""SparkTutor JSON-lines server entry point.

Usage: python -m sparktutor.server

Reads JSON requests from stdin (one per line), writes JSON responses to stdout.
All logging goes to stderr to keep the protocol clean.
"""

from __future__ import annotations

import asyncio
import json
import sys

from .handler import ServerHandler
from .protocol import Notification, Response


async def main() -> None:
    loop = asyncio.get_event_loop()

    def write_line(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def write_notification(notification: Notification) -> None:
        write_line(notification.to_json_line())

    handler = ServerHandler(write_notification=write_notification)

    # Log to stderr so stdout stays clean for protocol messages
    print("sparktutor-server: ready", file=sys.stderr)

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break  # stdin closed

        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            continue

        try:
            msg = json.loads(line_str)
        except json.JSONDecodeError as e:
            resp = Response(id=0, error=f"Invalid JSON: {e}")
            write_line(resp.to_json_line())
            continue

        req_id = msg.get("id", 0)
        try:
            result = await handler.dispatch(msg)
            resp = Response(id=req_id, result=result)
        except Exception as e:
            print(f"sparktutor-server: error: {e}", file=sys.stderr)
            resp = Response(id=req_id, error=str(e))

        write_line(resp.to_json_line())


if __name__ == "__main__":
    asyncio.run(main())
