# app/core/ai_assist.py

"""
AI-assisted matching enhancement.

Enhances the deterministic matching engine with AI capabilities:
1. Generate human-friendly explanations for all discrepancies
2. Suggest resolutions based on user history
3. Learn from user confirmations (future)
"""

from typing import Optional

from app.models import MatchDB, Resolution
from app.integrations import claude
from app.database import get_user_resolutions


async def enhance_matches_with_ai(
    matches: list[MatchDB],
    user_id: str,
) -> list[MatchDB]:
    """
    Enhance matches with AI-generated explanations and suggestions.
    
    Only processes matches that have discrepancies.
    """
    # Get user's resolution history for personalized suggestions
    user_history = await get_user_resolutions(user_id, limit=50)
    
    for match in matches:
        if match.has_discrepancy:
            # Generate AI explanation
            ai_explanation = await claude.explain_discrepancy(match)
            match.ai_explanation = ai_explanation
            
            # Get AI suggestion
            suggestion = await claude.suggest_resolution(match, user_history)
            match.ai_suggested_action = suggestion.get("action")
    
    return matches


async def get_ai_suggestion(
    match: MatchDB,
    user_id: str,
) -> dict:
    """
    Get AI suggestion for a specific match.
    
    Returns:
        {
            "action": "mark_as_expected" | etc,
            "confidence": 0.0-1.0,
            "reason": "explanation"
        }
    """
    user_history = await get_user_resolutions(user_id, limit=50)
    return await claude.suggest_resolution(match, user_history)


async def explain_match(match: MatchDB) -> str:
    """Get AI explanation for a specific match."""
    if match.has_discrepancy:
        return await claude.explain_discrepancy(match)
    return "This transaction matched successfully with high confidence."


async def analyze_patterns(
    user_id: str,
    matches: list[MatchDB],
) -> dict:
    """
    Analyze patterns in user's reconciliation data.
    
    Returns insights about:
    - Common discrepancy types
    - Recurring issues
    - Suggested process improvements
    """
    # Count discrepancy types
    type_counts = {}
    for match in matches:
        if match.has_discrepancy and match.discrepancy_type:
            type_counts[match.discrepancy_type] = type_counts.get(match.discrepancy_type, 0) + 1
    
    # Get most common type
    most_common = max(type_counts.items(), key=lambda x: x[1]) if type_counts else None
    
    insights = {
        "total_discrepancies": sum(type_counts.values()),
        "by_type": type_counts,
        "most_common": most_common[0] if most_common else None,
        "suggestions": [],
    }
    
    # Generate suggestions based on patterns
    if type_counts.get("fee_not_recorded", 0) > 5:
        insights["suggestions"].append({
            "type": "process",
            "message": "You have many unrecorded Stripe fees. Consider setting up automatic fee tracking in QuickBooks.",
        })
    
    if type_counts.get("timing_difference", 0) > 10:
        insights["suggestions"].append({
            "type": "settings",
            "message": "Many timing differences detected. Consider increasing your date tolerance from {settings.date_tolerance_days} days.",
        })
    
    return insights
