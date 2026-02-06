# app/core/confidence.py

"""
Confidence scoring for transaction matching.

Scoring breakdown (0-100):
- Amount match:    0-40 points
- Date proximity:  0-30 points  
- Customer match:  0-20 points
- Description:     0-10 points
"""

from datetime import date
import re
from app.models import ConfidenceBreakdown, ConfidenceLevel, TransactionCreate
from app.config import get_settings

settings = get_settings()

# Thresholds
HIGH_CONFIDENCE = settings.auto_match_threshold  # 85
MEDIUM_CONFIDENCE = 60


def calculate_confidence(
    stripe: TransactionCreate,
    qbo: TransactionCreate,
    date_tolerance_days: int = None,
) -> ConfidenceBreakdown:
    """
    Calculate match confidence between Stripe and QuickBooks transactions.
    
    Returns a ConfidenceBreakdown with scores and human-readable factors.
    """
    if date_tolerance_days is None:
        date_tolerance_days = settings.date_tolerance_days
    
    factors: list[str] = []
    
    # ============================================
    # Amount scoring (0-40 points)
    # ============================================
    amount_score = _score_amount(stripe.amount, qbo.amount, factors)
    
    # ============================================
    # Date scoring (0-30 points)
    # ============================================
    date_score = _score_date(stripe.transaction_date, qbo.transaction_date, factors)
    
    # ============================================
    # Customer scoring (0-20 points)
    # ============================================
    customer_score = _score_customer(
        stripe.customer_id, stripe.customer_name,
        qbo.customer_id, qbo.customer_name,
        factors
    )
    
    # ============================================
    # Description scoring (0-10 points)
    # ============================================
    description_score = _score_description(stripe.description, qbo.description, factors)
    
    # Calculate total and level
    total = amount_score + date_score + customer_score + description_score
    level = _get_confidence_level(total)
    
    return ConfidenceBreakdown(
        amount_score=amount_score,
        date_score=date_score,
        customer_score=customer_score,
        description_score=description_score,
        total=total,
        level=level,
        factors=factors,
    )


def _score_amount(stripe_amount: float, qbo_amount: float, factors: list[str]) -> int:
    """Score based on amount match (0-40 points)."""
    # Use absolute values to handle negative amounts (refunds)
    s_abs = abs(stripe_amount)
    q_abs = abs(qbo_amount)
    diff = abs(s_abs - q_abs)
    diff_percent = (diff / s_abs * 100) if s_abs > 0 else 100
    
    if diff < 0.01:
        factors.append("Exact amount match")
        return 40
    elif diff_percent <= 0.01:  # 0.01% - rounding errors
        factors.append("Amount within rounding tolerance")
        return 38
    elif diff_percent <= 1:
        factors.append(f"Amount within 1% (${diff:.2f} difference)")
        return 30
    elif diff_percent <= 3:
        factors.append(f"Amount within 3% (${diff:.2f} difference)")
        return 20
    elif diff_percent <= 5:
        factors.append(f"Amount within 5% (${diff:.2f} difference)")
        return 15
    elif diff_percent <= 10:
        factors.append(f"Amount differs by {diff_percent:.1f}%")
        return 8
    else:
        factors.append(f"Significant amount difference: {diff_percent:.1f}%")
        return 0


def _score_date(stripe_date: date, qbo_date: date, factors: list[str]) -> int:
    """Score based on date proximity (0-30 points)."""
    days_diff = abs((stripe_date - qbo_date).days)
    
    if days_diff == 0:
        factors.append("Same day")
        return 30
    elif days_diff == 1:
        factors.append("1 day apart")
        return 27
    elif days_diff <= 3:
        factors.append(f"{days_diff} days apart")
        return 22
    elif days_diff <= 7:
        factors.append(f"{days_diff} days apart (within week)")
        return 15
    elif days_diff <= 14:
        factors.append(f"{days_diff} days apart (within 2 weeks)")
        return 8
    elif days_diff <= 30:
        factors.append(f"{days_diff} days apart")
        return 3
    else:
        factors.append(f"{days_diff} days apart (significant gap)")
        return 0


def _score_customer(
    stripe_id: str | None,
    stripe_name: str | None,
    qbo_id: str | None,
    qbo_name: str | None,
    factors: list[str]
) -> int:
    """Score based on customer match (0-20 points)."""
    
    # Direct ID match (rare but perfect)
    if stripe_id and qbo_id and stripe_id == qbo_id:
        factors.append("Customer ID exact match")
        return 20
    
    # Name matching
    if stripe_name and qbo_name:
        stripe_normalized = _normalize_string(stripe_name)
        qbo_normalized = _normalize_string(qbo_name)
        
        # Exact match after normalization
        if stripe_normalized == qbo_normalized:
            factors.append("Customer name exact match")
            return 18
        
        # One contains the other
        if stripe_normalized in qbo_normalized or qbo_normalized in stripe_normalized:
            factors.append("Customer name partial match")
            return 14
        
        # Fuzzy match
        similarity = _fuzzy_similarity(stripe_normalized, qbo_normalized)
        if similarity > 0.8:
            factors.append("Customer name similar")
            return 10
        elif similarity > 0.6:
            factors.append("Customer name somewhat similar")
            return 5
    
    return 0


def _score_description(stripe_desc: str | None, qbo_desc: str | None, factors: list[str]) -> int:
    """Score based on description match (0-10 points)."""
    if not stripe_desc or not qbo_desc:
        return 0
    
    stripe_normalized = _normalize_string(stripe_desc)
    qbo_normalized = _normalize_string(qbo_desc)
    
    if stripe_normalized == qbo_normalized:
        factors.append("Description exact match")
        return 10
    
    # Check for common substrings
    if len(stripe_normalized) > 5 and len(qbo_normalized) > 5:
        if stripe_normalized in qbo_normalized or qbo_normalized in stripe_normalized:
            factors.append("Description partial match")
            return 7
        
        similarity = _fuzzy_similarity(stripe_normalized, qbo_normalized)
        if similarity > 0.7:
            factors.append("Description similar")
            return 5
        elif similarity > 0.5:
            return 2
    
    return 0


def _get_confidence_level(score: int) -> ConfidenceLevel:
    """Convert numeric score to confidence level."""
    if score >= HIGH_CONFIDENCE:
        return "high"
    elif score >= MEDIUM_CONFIDENCE:
        return "medium"
    else:
        return "low"


def _normalize_string(s: str) -> str:
    """Normalize string for comparison."""
    # Lowercase, remove special chars, collapse whitespace
    s = s.lower()
    s = re.sub(r'[^a-z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _fuzzy_similarity(s1: str, s2: str) -> float:
    """
    Calculate similarity between two strings.
    Returns 0.0 to 1.0.
    
    Using simple character overlap for speed.
    Could upgrade to Levenshtein distance later.
    """
    if not s1 or not s2:
        return 0.0
    
    # Character frequency comparison
    set1 = set(s1)
    set2 = set(s2)
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    if union == 0:
        return 0.0
    
    # Jaccard similarity
    jaccard = intersection / union
    
    # Also consider length similarity
    len_ratio = min(len(s1), len(s2)) / max(len(s1), len(s2))
    
    # Weighted average
    return (jaccard * 0.6) + (len_ratio * 0.4)
