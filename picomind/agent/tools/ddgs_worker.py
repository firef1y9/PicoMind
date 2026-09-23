"""Isolated DuckDuckGo worker.

The worker runs in a separate process so a stuck network request can be killed
without blocking the PicoMind event loop or leaving a non-cancellable thread.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        query = str(payload.get("query") or "").strip()
        limit = max(1, int(payload.get("limit") or 5))
        timeout = max(1, int(float(payload.get("timeout") or 10)))
        if not query:
            print("[]")
            return 0
        from ddgs import DDGS

        with DDGS(timeout=timeout) as client:
            results = list(client.text(query, max_results=limit))
        print(json.dumps(results, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
