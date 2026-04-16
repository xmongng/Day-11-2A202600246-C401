"""
Assignment 11 — Rate Limiter Plugin

Prevents abuse by limiting how many requests a single user can send
within a sliding time window.

Why this layer is needed:
    Other guardrails (injection detection, topic filter) only check message
    CONTENT. A rate limiter catches ABUSE PATTERNS — e.g., an attacker
    rapidly trying hundreds of prompt variations to find one that bypasses
    content filters. No content filter catches this; only rate limiting does.
"""
from collections import defaultdict, deque
import time

from google.genai import types
from google.adk.plugins import base_plugin


class RateLimitPlugin(base_plugin.BasePlugin):
    """Sliding-window rate limiter per user.

    How it works:
        - Maintains a deque of timestamps per user_id.
        - On each request, removes timestamps older than the window.
        - If remaining count >= max_requests, BLOCKS and returns wait time.
        - Otherwise, records the new timestamp and allows the request.

    Args:
        max_requests: Maximum requests allowed per window (default: 10)
        window_seconds: Time window in seconds (default: 60)
    """

    def __init__(self, max_requests=10, window_seconds=60):
        super().__init__(name="rate_limiter")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.user_windows = defaultdict(deque)
        self.blocked_count = 0
        self.total_count = 0

    def _block_response(self, message: str) -> types.Content:
        """Create a Content object with a block message."""
        return types.Content(
            role="model",
            parts=[types.Part.from_text(text=message)],
        )

    async def on_user_message_callback(
        self,
        *,
        invocation_context,
        user_message,
    ) -> types.Content | None:
        """Check if user has exceeded the rate limit.

        Returns:
            None if within limit (allow), types.Content if rate-limited (block).
        """
        self.total_count += 1

        # Extract user_id from invocation context (fallback to "anonymous")
        user_id = "anonymous"
        if invocation_context and hasattr(invocation_context, "user_id"):
            user_id = invocation_context.user_id or "anonymous"

        now = time.time()
        window = self.user_windows[user_id]

        # Remove timestamps that have expired (older than window_seconds)
        while window and window[0] <= now - self.window_seconds:
            window.popleft()

        # Check if user has exceeded the limit
        if len(window) >= self.max_requests:
            self.blocked_count += 1
            # Calculate how long the user needs to wait
            oldest = window[0]
            wait_time = round(oldest + self.window_seconds - now, 1)
            print(f"  [RATE LIMITED] User '{user_id}' exceeded {self.max_requests} "
                  f"requests in {self.window_seconds}s. Wait {wait_time}s.")
            return self._block_response(
                f"⚠️ Rate limit exceeded. You've sent too many requests. "
                f"Please wait {wait_time} seconds before trying again."
            )

        # Within limit — record this request and allow
        window.append(now)
        return None
