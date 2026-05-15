"""
Bearer-token auth for the FastAPI surface.

One static token shared between the Railway service and the Base44 frontend.
Rotated by changing API_TOKEN env var on both sides — no DB, no JWT, no
moving parts. Right tradeoff for a single-consumer internal API.

Also includes a tiny in-process rate limiter for `/insights/weekly` to cap
Haiku spend at runaway-loop scale (genuine burst protection, not security).
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import Header, HTTPException, status

from .config import settings


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        # Fail closed — never serve unauthenticated when the env wasn't set.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_TOKEN not configured on server",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    # Constant-time compare — paranoid for a 43-char shared secret, costs nothing.
    if not _consteq(token, settings.api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _consteq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0


# ---- in-process rate limiter (Haiku spend protection) ------------------------

class _SlidingWindow:
    def __init__(self, max_calls: int, window_seconds: int) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls: deque[float] = deque()
        self.lock = Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.calls and self.calls[0] < now - self.window:
                self.calls.popleft()
            if len(self.calls) >= self.max_calls:
                return False
            self.calls.append(now)
            return True


# 30 calls per hour is generous for a dashboard refresh — protects against
# a Base44 component re-render loop hitting Haiku 1000x.
_weekly_limiter = _SlidingWindow(max_calls=30, window_seconds=3600)


def rate_limit_weekly() -> None:
    if not _weekly_limiter.allow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit: max 30 calls/hour to /insights/weekly (Haiku spend cap)",
        )
