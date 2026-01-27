# app/integrations/claude.py

"""
Claude AI integration for intelligent explanations and suggestions.

Uses Anthropic's Claude API to:
1. Generate human-readable explanations for discrepancies
2. Suggest resolutions based on user history
3. Detect anomalies in transaction patterns
"""

import json
from typing import Optional
from anthropic import Anthropic

from app.config import get_settings
from app.models import MatchDB, Resolution

settings = get_settings()

# Initialize client
client = Anthropic(api_key=settings.anthropic_api_key)

# Model to use
MODEL = "claude-sonnet-4-20250514"


async def explain_discrepancy(match: MatchDB) -> str:
    """
    Generate a human-readable explanation for a discrepancy.
    
    Takes a match with a discrepancy and returns a clear, actionable explanation.
    """
    if not settings.enable_ai_explanations:
        return match.discrepancy_explanation or ""
    
    prompt = f"""You are a financial reconciliation assistant for Mesh, a tool that helps 
finance teams match Stripe payments with QuickBooks entries.

Analyze this discrepancy and explain it in plain English. Be concise (2-3 sentences max).
Write like a helpful colleague, not a robot. Be specific and actionable.

STRIPE TRANSACTION:
- ID: {match.stripe_external_id}
- Amount: ${match.confidence_breakdown.get('stripe_amount', 'N/A')}

QUICKBOOKS ENTRY:
- ID: {match.qbo_external_id or 'MISSING'}
- Amount: ${match.confidence_breakdown.get('qbo_amount', 'N/A')}

DETECTED ISSUE: {match.discrepancy_type}
AMOUNT DIFFERENCE: ${match.amount_difference or 0:,.2f}
DATE DIFFERENCE: {match.date_difference_days or 0} days

SYSTEM EXPLANATION: {match.discrepancy_explanation}

Rewrite the explanation to be more human-friendly and actionable. 
Don't repeat the data - focus on what happened and what to do."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        # Fall back to system explanation
        print(f"Claude API error: {e}")
        return match.discrepancy_explanation or "Review this discrepancy manually."


async def suggest_resolution(
    match: MatchDB,
    user_history: list[Resolution],
) -> dict:
    """
    Suggest a resolution based on user's past behavior.
    
    Returns:
        {
            "action": "mark_as_expected" | "flag_for_review" | etc,
            "confidence": 0.0-1.0,
            "reason": "explanation"
        }
    """
    if not settings.enable_ai_suggestions:
        return {
            "action": "flag_for_review",
            "confidence": 0.5,
            "reason": "AI suggestions disabled"
        }
    
    # Build context from user's history
    history_context = "No previous resolutions recorded."
    if user_history:
        history_lines = []
        for r in user_history[-10:]:  # Last 10 resolutions
            history_lines.append(f"- {r.discrepancy_type}: User chose '{r.action}'")
        history_context = "\n".join(history_lines)
    
    prompt = f"""Based on how this user has resolved similar discrepancies in the past,
what action would you recommend for this new discrepancy?

USER'S PAST RESOLUTIONS:
{history_context}

NEW DISCREPANCY:
- Type: {match.discrepancy_type}
- Severity: {match.discrepancy_severity}
- Amount difference: ${match.amount_difference or 0:,.2f}
- Explanation: {match.discrepancy_explanation}
- Auto-resolvable: {match.discrepancy_auto_resolvable}

Available actions:
- mark_as_expected: This is normal, no fix needed
- flag_for_review: Needs investigation
- create_qbo_entry: Create missing QuickBooks entry
- adjust_amount: Record an adjustment/fee
- ignore_permanently: Never show this again

Respond with JSON only: {{"action": "...", "confidence": 0.0-1.0, "reason": "..."}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Parse JSON response
        text = response.content[0].text
        # Clean up potential markdown formatting
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0]
        
        return json.loads(text)
    except Exception as e:
        print(f"Claude API error: {e}")
        # Default suggestion based on discrepancy type
        return _get_default_suggestion(match)


async def batch_explain(matches: list[MatchDB]) -> list[str]:
    """
    Generate explanations for multiple discrepancies.
    
    For MVP, this processes sequentially. 
    Could be optimized with async gather later.
    """
    explanations = []
    for match in matches:
        if match.has_discrepancy:
            explanation = await explain_discrepancy(match)
            explanations.append(explanation)
        else:
            explanations.append("")
    return explanations


async def detect_anomaly(
    transaction_amount: float,
    historical_amounts: list[float],
) -> Optional[dict]:
    """
    Detect if a transaction is anomalous compared to history.
    
    Returns anomaly info if detected, None otherwise.
    """
    if not historical_amounts:
        return None
    
    avg = sum(historical_amounts) / len(historical_amounts)
    
    # Simple threshold check (could be more sophisticated)
    if transaction_amount > avg * 5:
        return {
            "type": "unusually_large",
            "message": f"This ${transaction_amount:,.2f} transaction is {transaction_amount/avg:.1f}x your average (${avg:,.2f}). Worth a second look.",
            "severity": "warning",
        }
    
    return None


def _get_default_suggestion(match: MatchDB) -> dict:
    """Get default suggestion based on discrepancy type."""
    
    type_to_action = {
        "fee_not_recorded": ("adjust_amount", 0.8, "Fee discrepancies are usually resolved by recording the fee"),
        "timing_difference": ("mark_as_expected", 0.7, "Timing differences are often acceptable"),
        "missing_in_qbo": ("create_qbo_entry", 0.6, "Missing entries typically need to be created"),
        "amount_mismatch": ("flag_for_review", 0.5, "Amount mismatches need manual review"),
    }
    
    action, confidence, reason = type_to_action.get(
        match.discrepancy_type,
        ("flag_for_review", 0.5, "Unclear discrepancy - needs review")
    )
    
    return {
        "action": action,
        "confidence": confidence,
        "reason": reason,
    }
