"""SparkTutor JSON-lines server entry point.

Usage: python -m sparktutor.server

Reads JSON requests from stdin (one per line), writes JSON responses to stdout.
All logging goes to stderr to keep the protocol clean.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading

from .handler import ServerHandler
from .protocol import Notification, Response


def write_line(text: str) -> None:
    """Write a UTF-8 line to stdout.

    We write raw bytes instead of ``sys.stdout.write`` so the protocol stream
    is always UTF-8 regardless of the Windows console / locale encoding.
    """
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


async def main() -> None:
    loop = asyncio.get_event_loop()

    def write_notification(notification: Notification) -> None:
        write_line(notification.to_json_line())

    handler = ServerHandler(write_notification=write_notification)

    # Log to stderr so stdout stays clean for protocol messages
    print("sparktutor-server: ready", file=sys.stderr)

    # On Windows, `loop.connect_read_pipe(sys.stdin)` uses the Proactor
    # read-pipe transport, which crashes on Python 3.12 with
    # "OSError: [WinError 6] The handle is invalid" for anonymous pipe
    # handles (the handle created by VS Code's subprocess spawn). To stay
    # portable, read stdin on a background thread instead and feed lines into
    # an asyncio queue. Request handling remains serialized in the event loop,
    # exactly as the previous while-loop did.
    lines: asyncio.Queue[str] = asyncio.Queue()

    def read_stdin() -> None:
        try:
            for raw in sys.stdin.buffer:
                line_str = raw.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                loop.call_soon_threadsafe(lines.put_nowait, line_str)
        finally:
            # Sentinel: signal the event loop to stop when stdin closes.
            loop.call_soon_threadsafe(lines.put_nowait, None)

    threading.Thread(
        target=read_stdin, name="sparktutor-stdin", daemon=True
    ).start()

    while True:
        line_str = await lines.get()
        if line_str is None:
            break  # stdin closed

        try:
            msg = json.loads(line_str)
        except json.JSONDecodeError as e:
            resp = Response(id=0, error=f"Invalid JSON: {e}")
            write_line(resp.to_json_line())
        else:
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
