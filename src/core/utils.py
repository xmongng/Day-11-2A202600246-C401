"""
Lab 11 — Helper Utilities

Pipeline flow (manual orchestration with ChatNVIDIA):
    1. Record input in Audit Log (ALWAYS, even if blocked later)
    2. Run input guardrails via on_user_message_callback (rate limiter, injection, topic)
       - If blocked → use the blocked message as the response text
    3. Call LLM (Langchain ChatNVIDIA streaming)
    4. Run output guardrails DIRECTLY as function calls:
       - content_filter() → PII/secret redaction
       - llm_judge_check() → multi-criteria evaluation
    5. Record output in Audit Log (ALWAYS)
    6. Return response text string

Key design decisions:
    - Audit log is called FIRST (before guardrails) and LAST (after guardrails)
      so that ALL interactions are recorded, including blocked ones.
    - Input guardrails use the ADK plugin on_user_message_callback pattern.
    - Output guardrails are called as DIRECT functions to avoid type issues.
    - Response is tracked as a plain string throughout the pipeline.
"""
from google.genai import types


class DummyContext:
    """Minimal InvocationContext replacement for testing without ADK runtime."""
    user_id = "student"


class DummyLLMResponse:
    """Wrapper that mimics ADK LLM response structure for AuditLogPlugin."""
    def __init__(self, text: str):
        self.content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)]
        )


def _find_plugin(plugins, name):
    """Find a plugin by name in the plugin list."""
    for p in plugins:
        if getattr(p, 'name', '') == name:
            return p
    return None


async def chat_with_agent(client, context, user_message: str, session_id=None):
    """Send a message through the defense pipeline and get the response.

    This function manually orchestrates the entire pipeline:
        Layer 1: Rate Limiter (plugin callback)
        Layer 2: Input Guardrails (plugin callback)
        Layer 3: LLM call (ChatNVIDIA streaming)
        Layer 4: Output Guardrails (direct function calls)
        Layer 5: Audit Log (always records, even blocked requests)

    Args:
        client: The Langchain ChatNVIDIA instance
        context: A dictionary containing 'instruction' and 'plugins'
        user_message: Plain text message to send
        session_id: Optional session ID (unused, kept for API compatibility)

    Returns:
        Tuple of (response_text: str, session: None)
    """
    plugins = context.get('plugins', [])
    instruction = context.get('instruction', "")
    invocation_context = DummyContext()

    # ============================================================
    # Step 0: Record input in Audit Log FIRST (before any blocking)
    # This ensures ALL requests are logged, even rate-limited ones.
    # ============================================================
    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    )
    audit_plugin = _find_plugin(plugins, 'audit_log')
    if audit_plugin and hasattr(audit_plugin, 'on_user_message_callback'):
        await audit_plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_content
        )

    # ============================================================
    # Step 1: Run input guardrails (rate limiter + injection + topic)
    # Skip audit_log here since we already called it above.
    # ============================================================
    response_text = ""
    was_blocked = False

    for plugin in plugins:
        # Skip audit_log (already handled above)
        if getattr(plugin, 'name', '') == 'audit_log':
            continue
        if hasattr(plugin, 'on_user_message_callback'):
            result = await plugin.on_user_message_callback(
                invocation_context=invocation_context,
                user_message=user_content
            )
            if result is not None:
                was_blocked = True
                if result.parts:
                    response_text = result.parts[0].text or ""
                break

    # ============================================================
    # Step 2: Call LLM (only if not blocked at input)
    # ============================================================
    if not was_blocked:
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=instruction),
            HumanMessage(content=user_message)
        ]

        try:
            async for chunk in client.astream(messages):
                if chunk.content:
                    response_text += chunk.content
        except (NotImplementedError, AttributeError):
            for chunk in client.stream(messages):
                if chunk.content:
                    response_text += chunk.content

    # ============================================================
    # Step 3: Output Guardrails — called DIRECTLY as functions
    # Only run on non-blocked responses (blocked responses are
    # already safe guardrail messages).
    # ============================================================
    if not was_blocked and response_text:
        from guardrails.output_guardrails import content_filter, llm_judge_check

        output_plugin = _find_plugin(plugins, 'output_guardrail')

        # Step 3a: Content filter (regex PII/secrets)
        filter_result = content_filter(response_text)
        if not filter_result["safe"]:
            response_text = filter_result["redacted"]
            if output_plugin:
                output_plugin.redacted_count += 1
            print(f"  [REDACTED] {filter_result['issues']}")

        # Step 3b: LLM-as-Judge (multi-criteria)
        if output_plugin:
            output_plugin.total_count += 1
            if output_plugin.use_llm_judge:
                judge_result = await llm_judge_check(response_text)
                output_plugin.judge_results.append(judge_result)

                print(f"  [JUDGE] Safety={judge_result['safety']} | "
                      f"Relevance={judge_result['relevance']} | "
                      f"Accuracy={judge_result['accuracy']} | "
                      f"Tone={judge_result['tone']} | "
                      f"Verdict={judge_result['verdict']}")

                # Block only if SAFETY is critically low (harmful content).
                # A FAIL verdict from low Accuracy alone (e.g., hallucinated
                # interest rates) should NOT block — it's not a safety issue.
                safety_score = judge_result.get("safety", 5)
                if judge_result["verdict"].upper() == "FAIL" and safety_score <= 2:
                    output_plugin.blocked_count += 1
                    response_text = ("I'm sorry, but I cannot provide that response. "
                                     "Please contact VinBank support directly.")

    # ============================================================
    # Step 4: Record output in Audit Log (ALWAYS — blocked or not)
    # ============================================================
    if audit_plugin and hasattr(audit_plugin, 'after_model_callback'):
        llm_response_wrapper = DummyLLMResponse(text=response_text)
        await audit_plugin.after_model_callback(
            callback_context=None,
            llm_response=llm_response_wrapper
        )

    return response_text, None
