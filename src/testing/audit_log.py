"""
Assignment 11 — Audit Log Plugin

Records every interaction: input, output, which layer blocked it,
latency, and timestamp. Exports to JSON for analysis.

Why this layer is needed:
    Guardrails block attacks silently. Without an audit log, you have no
    visibility into WHAT was blocked, WHEN, and WHY. In production banking,
    audit trails are legally required for compliance (PCI-DSS, SOX).
    No other layer provides this historical record.

Key design:
    - on_user_message_callback: records input + starts latency timer
    - after_model_callback: records output + calculates latency
    - Both blocked AND allowed requests are logged (visibility into attacks)
    - Input guardrail blocks are detected by checking if the response
      starts with a block message (injected by input guardrail)
"""

import json
import time
from datetime import datetime

from google.genai import types
from google.adk.plugins import base_plugin


# Block message prefixes used by input guardrails
INPUT_BLOCK_PREFIXES = [
    "i cannot process that message",
    "i'm a vinbank assistant",
    "i can only help with banking-related",
    "i can only help with banking related",
]


class AuditLogPlugin(base_plugin.BasePlugin):
    """Records all interactions for security auditing and compliance.

    Captures:
        - User input text
        - Agent response text
        - Whether input was blocked (and by which layer)
        - Processing latency
        - Timestamp

    This plugin NEVER blocks or modifies messages — it only observes.
    """

    def __init__(self):
        super().__init__(name="audit_log")
        self.logs = []
        self._pending = {}  # Track in-progress requests by request_id
        self._request_counter = 0

    def _extract_text(self, content) -> str:
        """Extract plain text from a Content or DummyLLMResponse object."""
        text = ""
        # Handle DummyLLMResponse (has .content.parts)
        if hasattr(content, "content") and content.content:
            parts = getattr(content.content, "parts", [])
            for part in (parts or []):
                if hasattr(part, "text") and part.text:
                    text += part.text
            if text:
                return text
        # Handle types.Content directly (has .parts)
        if hasattr(content, "parts") and content.parts:
            for part in content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
        return text

    def _detect_blocked_by_input_guard(self, response_text: str) -> bool:
        """Detect if response was blocked by an input guardrail.

        Input guardrails inject a types.Content response to block requests.
        We detect this by checking if the response matches known block patterns.
        """
        r = response_text.lower()
        return any(r.startswith(p) for p in INPUT_BLOCK_PREFIXES)

    async def on_user_message_callback(
        self,
        *,
        invocation_context,
        user_message,
    ) -> types.Content | None:
        """Record the user's input and start the latency timer.

        Never blocks — always returns None.
        """
        user_id = "anonymous"
        if invocation_context and hasattr(invocation_context, "user_id"):
            user_id = invocation_context.user_id or "anonymous"

        self._request_counter += 1
        request_id = f"{user_id}_{self._request_counter}"
        text = self._extract_text(user_message)

        self._pending[request_id] = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "user_id": user_id,
            "input": text,
            "output": "",
            "blocked": False,
            "blocked_by": None,
            "start_time": time.time(),
            "latency_ms": 0,
        }

        return None  # Never block

    async def after_model_callback(
        self,
        *,
        callback_context,  # noqa: ARG001 — required by ADK plugin interface
        llm_response,
    ):
        """Record the agent's response and calculate latency.

        Never modifies — always returns the original response.
        """
        if not self._pending:
            return llm_response

        # Get most recent pending entry
        request_id = list(self._pending.keys())[-1]
        entry = self._pending.pop(request_id)

        # Extract response text
        response_text = self._extract_text(llm_response)
        entry["output"] = response_text[:500]  # Truncate for storage

        # Detect if input guardrail blocked this request
        if self._detect_blocked_by_input_guard(response_text):
            entry["blocked"] = True
            entry["blocked_by"] = "input_guardrail"

        # Calculate latency
        entry["latency_ms"] = round((time.time() - entry.pop("start_time")) * 1000, 1)

        # Remove internal fields before storing
        entry.pop("request_id", None)
        entry.pop("start_time", None)

        self.logs.append(entry)

        return llm_response  # Never modify

    def log_block(self, user_id: str, input_text: str, blocked_by: str, reason: str):
        """Manually log a blocked request (called by rate limiter or other plugins).

        Args:
            user_id: The user who was blocked
            input_text: The blocked input text
            blocked_by: Name of the layer that blocked it
            reason: Why it was blocked
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "input": input_text[:500],
            "output": f"[BLOCKED by {blocked_by}] {reason}",
            "blocked": True,
            "blocked_by": blocked_by,
            "latency_ms": 0,
        }
        self.logs.append(entry)

        # Clean up any pending entry for this user
        key_to_remove = None
        for k, v in self._pending.items():
            if v.get("user_id") == user_id:
                key_to_remove = k
                break
        if key_to_remove:
            self._pending.pop(key_to_remove, None)

    def export_json(self, filepath="audit_log.json"):
        """Export all logs to a JSON file.

        Args:
            filepath: Output file path (default: audit_log.json)
        """
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.logs, f, indent=2, default=str, ensure_ascii=False)
        print(f"Audit log exported: {filepath} ({len(self.logs)} entries)")

    def get_summary(self) -> dict:
        """Get a summary of the audit log metrics."""
        total = len(self.logs)
        blocked = sum(1 for e in self.logs if e.get("blocked"))

        # Group blocked by layer
        by_layer = {}
        for e in self.logs:
            layer = e.get("blocked_by") or "none"
            by_layer[layer] = by_layer.get(layer, 0) + 1

        return {
            "total_entries": total,
            "blocked_entries": blocked,
            "allowed_entries": total - blocked,
            "block_rate": round(blocked / total, 3) if total > 0 else 0,
            "by_layer": by_layer,
            "avg_latency_ms": round(
                sum(e.get("latency_ms", 0) for e in self.logs) / total, 1
            ) if total > 0 else 0,
        }
