# app/models/match.py

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field

from app.models.transaction import Transaction


# ============================================
# Confidence Scoring
# ============================================

ConfidenceLevel = Literal["high", "medium", "low"]

class ConfidenceBreakdown(BaseModel):
    """Breakdown of how confidence score was calculated."""
    
    amount_score: int = Field(ge=0, le=40, description="0-40 points for amount match")
    date_score: int = Field(ge=0, le=30, description="0-30 points for date proximity")
    customer_score: int = Field(ge=0, le=20, description="0-20 points for customer match")
    description_score: int = Field(ge=0, le=10, description="0-10 points for description match")
    total: int = Field(ge=0, le=100, description="Total confidence score")
    level: ConfidenceLevel
    factors: list[str] = Field(default_factory=list, description="Human-readable factors")


# ============================================
# Discrepancy Classification
# ============================================

DiscrepancyType = Literal[
    "timing_difference",
    "amount_mismatch",
    "fee_not_recorded",
    "partial_payment",
    "duplicate_entry",
    "missing_in_qbo",
    "missing_in_stripe",
    "currency_conversion",
    "refund_not_recorded",
    "unknown",
]

DiscrepancySeverity = Literal["critical", "warning", "info"]

class DiscrepancyClassification(BaseModel):
    """Classification of a discrepancy."""
    
    type: DiscrepancyType
    severity: DiscrepancySeverity
    explanation: str
    suggested_action: str
    auto_resolvable: bool = False
    amount_difference: Optional[float] = None
    date_difference_days: Optional[int] = None
    
    # AI-generated fields
    ai_explanation: Optional[str] = None
    ai_suggested_action: Optional[str] = None


# ============================================
# Match
# ============================================

MatchStatus = Literal["auto_matched", "suggested", "confirmed", "rejected", "resolved"]

class Match(BaseModel):
    """A matched pair of transactions."""
    
    id: str
    stripe_transaction: Transaction
    qbo_transaction: Optional[Transaction] = None
    confidence: ConfidenceBreakdown
    match_reason: str
    matched_at: datetime
    status: MatchStatus
    discrepancy: Optional[DiscrepancyClassification] = None
    
    class Config:
        from_attributes = True


class MatchDB(BaseModel):
    """Match as stored in database."""
    
    id: Optional[str] = None
    user_id: str
    stripe_external_id: str
    qbo_external_id: Optional[str] = None
    
    confidence_total: int
    confidence_level: ConfidenceLevel
    confidence_breakdown: dict
    
    match_reason: str
    status: MatchStatus = "auto_matched"
    
    has_discrepancy: bool = False
    discrepancy_type: Optional[DiscrepancyType] = None
    discrepancy_severity: Optional[DiscrepancySeverity] = None
    discrepancy_explanation: Optional[str] = None
    discrepancy_suggested_action: Optional[str] = None
    discrepancy_auto_resolvable: bool = False
    amount_difference: Optional[float] = None
    date_difference_days: Optional[int] = None
    
    # AI fields
    ai_explanation: Optional[str] = None
    ai_suggested_action: Optional[str] = None
    
    class Config:
        from_attributes = True


# ============================================
# Unmatched Transaction
# ============================================

class PossibleMatch(BaseModel):
    """A potential match candidate."""
    
    transaction: Transaction
    confidence: ConfidenceBreakdown
    why_not_auto_matched: str


class UnmatchedTransaction(BaseModel):
    """A transaction that couldn't be matched."""
    
    transaction: Transaction
    possible_matches: list[PossibleMatch] = Field(default_factory=list)
    classification: DiscrepancyClassification
    days_old: int
    priority: Literal["high", "medium", "low"]


# ============================================
# API Response Models
# ============================================

class MatchResponse(BaseModel):
    """Single match response."""
    
    id: str
    customer_name: str
    stripe_id: str
    stripe_amount: float
    qbo_amount: Optional[float]
    confidence: int
    confidence_level: ConfidenceLevel
    status: MatchStatus
    
    has_discrepancy: bool
    discrepancy_type: Optional[str] = None
    severity: Optional[str] = None
    explanation: Optional[str] = None
    suggested_action: Optional[str] = None
    auto_resolvable: bool = False
    
    # AI-enhanced
    ai_explanation: Optional[str] = None


class MatchListResponse(BaseModel):
    """List of matches response."""
    
    success: bool
    matches: list[MatchResponse]
    pagination: dict


class DiscrepancySummary(BaseModel):
    """Summary of discrepancies."""
    
    critical: int
    warning: int
    info: int
    total: int
