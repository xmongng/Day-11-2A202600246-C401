"""
Assignment 11 — Audit Log Plugin

Records every interaction: input, output, which layer blocked it,
latency, and timestamp. Exports to JSON for analysis.

Why this layer is needed:
    Guardrails block attacks silently. Without an audit log, you have no
    visibility into WHAT was blocked, WHEN, and WHY. In production banking,
    audit trails are legally required for compliance (PCI-DSS, SOX).
    No other layer provides this historical record.
"""
import json
import time
from datetime import datetime

from google.genai import types
from google.adk.plugins import base_plugin


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
        self._pending = {}  # Track in-progress requests by user_id

    def _extract_text(self, content) -> str:
        """Extract plain text from a Content object."""
        text = ""
        if content and hasattr(content, "parts") and content.parts:
            for part in content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
        return text

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

        text = self._extract_text(user_message)

        self._pending[user_id] = {
            "timestamp": datetime.now().isoformat(),
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
        callback_context,
        llm_response,
    ):
        """Record the agent's response and calculate latency.

        Never modifies — always returns the original response.
        """
        # Try to find the pending record
        user_id = "anonymous"
        if self._pending:
            # Get the most recent pending entry
            user_id = list(self._pending.keys())[-1]

        if user_id in self._pending:
            entry = self._pending.pop(user_id)

            # Extract response text
            response_text = ""
            if hasattr(llm_response, "content") and llm_response.content:
                for part in llm_response.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text

            entry["output"] = response_text[:500]  # Truncate for storage
            entry["latency_ms"] = round((time.time() - entry.pop("start_time")) * 1000)
            self.logs.append(entry)

        return llm_response  # Never modify

    def log_block(self, user_id: str, input_text: str, blocked_by: str, reason: str):
        """Manually log a blocked request (called by other plugins).

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
        self._pending.pop(user_id, None)

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
        avg_latency = (
            sum(e.get("latency_ms", 0) for e in self.logs) / total
            if total > 0 else 0
        )
        return {
            "total_entries": total,
            "blocked_entries": blocked,
            "allowed_entries": total - blocked,
            "avg_latency_ms": round(avg_latency, 1),
        }
