"""
Lab 11 — Part 4: Human-in-the-Loop Design
  TODO 12: Confidence Router — COMPLETED
  TODO 13: Design 3 HITL decision points — COMPLETED
"""
from dataclasses import dataclass


# ============================================================
# TODO 12: Confidence Router — COMPLETED
#
# Why needed:
#   Not all AI responses are equally certain. Low-confidence responses
#   (e.g., complex financial advice) or high-risk actions (e.g., large
#   transfers) should ALWAYS involve a human before being sent to the user.
#   This prevents both hallucinations and irreversible financial errors.
# ============================================================

HIGH_RISK_ACTIONS = [
    "transfer_money",
    "close_account",
    "change_password",
    "delete_data",
    "update_personal_info",
]


@dataclass
class RoutingDecision:
    """Result of the confidence router."""
    action: str          # "auto_send", "queue_review", "escalate"
    confidence: float
    reason: str
    priority: str        # "low", "normal", "high"
    requires_human: bool


class ConfidenceRouter:
    """Route agent responses based on confidence score and action risk level.

    Why needed:
        A single threshold is too blunt. Banking requires nuance:
        - Balance inquiry at 0.95 confidence? Auto-send — low risk.
        - Loan advice at 0.75 confidence? Queue for human review.
        - Any money transfer request? Always escalate — irreversible action.

    Thresholds:
        HIGH:   confidence >= 0.9 → auto-send (safe to respond automatically)
        MEDIUM: 0.7 <= confidence < 0.9 → queue for human review
        LOW:    confidence < 0.7 → escalate immediately (too uncertain)

    High-risk actions always escalate regardless of confidence score.
    """

    HIGH_THRESHOLD = 0.9
    MEDIUM_THRESHOLD = 0.7

    def route(self, response: str, confidence: float,
              action_type: str = "general") -> RoutingDecision:
        """Route a response based on confidence score and action type.

        Args:
            response: The agent's response text (used for logging context)
            confidence: Confidence score between 0.0 and 1.0
            action_type: Type of action (e.g., "general", "transfer_money")

        Returns:
            RoutingDecision with routing action and metadata
        """
        # Special case: HIGH_RISK actions ALWAYS escalate, no exceptions.
        # Why: Even a 99% confident AI should not autonomously close accounts
        # or move money — these actions are irreversible.
        if action_type in HIGH_RISK_ACTIONS:
            return RoutingDecision(
                action="escalate",
                confidence=confidence,
                reason=f"High-risk action requires human approval: '{action_type}'",
                priority="high",
                requires_human=True,
            )

        # Normal routing by confidence threshold
        if confidence >= self.HIGH_THRESHOLD:
            # High confidence — safe to auto-send
            return RoutingDecision(
                action="auto_send",
                confidence=confidence,
                reason="High confidence — response sent automatically",
                priority="low",
                requires_human=False,
            )
        elif confidence >= self.MEDIUM_THRESHOLD:
            # Medium confidence — queue for async human review
            return RoutingDecision(
                action="queue_review",
                confidence=confidence,
                reason="Medium confidence — queued for human review before sending",
                priority="normal",
                requires_human=True,
            )
        else:
            # Low confidence — escalate immediately (uncertain answer)
            return RoutingDecision(
                action="escalate",
                confidence=confidence,
                reason="Low confidence — escalating to human agent immediately",
                priority="high",
                requires_human=True,
            )


# ============================================================
# TODO 13: Design 3 HITL decision points — COMPLETED
#
# A HITL "decision point" is a specific moment in the AI workflow
# where a human MUST or SHOULD review before proceeding.
#
# Three HITL models:
#   - human-in-the-loop:     Human must approve BEFORE action executes
#   - human-on-the-loop:     AI acts, human reviews AFTER and can override
#   - human-as-tiebreaker:   Two AI models disagree; human casts final vote
# ============================================================

hitl_decision_points = [
    {
        "id": 1,
        "name": "Large Transaction Approval",
        "trigger": (
            "Customer requests a transfer or withdrawal exceeding 50 million VND, "
            "OR any international wire transfer, OR a transaction to a new/unverified recipient."
        ),
        "hitl_model": "human-in-the-loop",
        "context_needed": (
            "Full transaction details (sender, recipient, amount, timestamp), "
            "customer's 90-day transaction history, recipient risk score, "
            "and the AI's reasoning for approving or flagging the request."
        ),
        "example": (
            "Customer: 'Transfer 200 million VND to account 123456789 at BIDV.' "
            "→ AI flags it as a large transfer to a new recipient. "
            "→ A bank operator reviews the request and calls the customer for verbal confirmation "
            "before the transaction is executed."
        ),
    },
    {
        "id": 2,
        "name": "Sensitive Account Change Review",
        "trigger": (
            "Customer requests a change to security-critical account settings: "
            "password reset, phone number update, email change, or adding a new device."
        ),
        "hitl_model": "human-on-the-loop",
        "context_needed": (
            "Change request details, customer authentication method used (OTP, face ID), "
            "login location and device fingerprint, and any recent failed login attempts "
            "in the last 24 hours."
        ),
        "example": (
            "Customer resets their password via chatbot at 2 AM from a new device in a foreign city. "
            "→ AI processes the request and sends confirmation. "
            "→ A security analyst is alerted on-the-loop and has a 15-minute window to block "
            "the change if the activity pattern is flagged as suspicious."
        ),
    },
    {
        "id": 3,
        "name": "Ambiguous Complaint or Dispute Resolution",
        "trigger": (
            "AI safety judge scores below 3/5 on 'ACCURACY' or 'RELEVANCE', "
            "OR the customer explicitly says 'I want to speak to a human', "
            "OR the customer asks about a disputed transaction exceeding 5 million VND."
        ),
        "hitl_model": "human-as-tiebreaker",
        "context_needed": (
            "Full conversation transcript, both AI responses (original and alternative), "
            "the specific dispute amount, and relevant transaction records from the core banking system."
        ),
        "example": (
            "Customer: 'I was charged twice for the same ATM withdrawal.' "
            "→ AI Model A says: 'No duplicate detected in our records.' "
            "→ AI Model B says: 'Possible duplicate detected — investigate.' "
            "→ The two models conflict. A human support agent reviews both responses "
            "alongside the actual transaction logs and makes the final determination."
        ),
    },
]


# ============================================================
# Quick tests
# ============================================================

def test_confidence_router():
    """Test ConfidenceRouter with realistic banking scenarios."""
    router = ConfidenceRouter()

    test_cases = [
        ("Balance inquiry", 0.95, "general"),
        ("Interest rate question", 0.82, "general"),
        ("Ambiguous loan advice", 0.55, "general"),
        ("Transfer $50,000", 0.98, "transfer_money"),   # High confidence but HIGH RISK
        ("Close my account", 0.91, "close_account"),    # High confidence but HIGH RISK
    ]

    print("Testing ConfidenceRouter:")
    print("=" * 85)
    print(f"{'Scenario':<25} {'Conf':<6} {'Action Type':<20} {'Decision':<15} {'Priority':<10} {'Human?'}")
    print("-" * 85)

    for scenario, conf, action_type in test_cases:
        decision = router.route(scenario, conf, action_type)
        print(
            f"{scenario:<25} {conf:<6.2f} {action_type:<20} "
            f"{decision.action:<15} {decision.priority:<10} "
            f"{'Yes ⚠' if decision.requires_human else 'No ✓'}"
        )
        print(f"  └─ Reason: {decision.reason}")

    print("=" * 85)


def test_hitl_points():
    """Display the 3 designed HITL decision points."""
    print("\nHITL Decision Points:")
    print("=" * 70)
    for point in hitl_decision_points:
        print(f"\n  Decision Point #{point['id']}: {point['name']}")
        print(f"    Trigger:  {point['trigger'][:100]}...")
        print(f"    Model:    {point['hitl_model']}")
        print(f"    Context:  {point['context_needed'][:100]}...")
        print(f"    Example:  {point['example'][:120]}...")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_confidence_router()
    test_hitl_points()
