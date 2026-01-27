# app/models/resolution.py

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel


# ============================================
# Resolution Actions
# ============================================

ResolutionAction = Literal[
    "mark_as_expected",
    "flag_for_review",
    "create_qbo_entry",
    "ignore_permanently",
    "manual_match",
    "split_transaction",
    "adjust_amount",
]


# ============================================
# Resolution Models
# ============================================

class ResolutionCreate(BaseModel):
    """Request to resolve a match."""
    
    user_id: str
    action: ResolutionAction
    notes: Optional[str] = None
    adjustment_amount: Optional[float] = None


class Resolution(BaseModel):
    """A resolution record."""
    
    id: str
    match_id: str
    user_id: str
    action: ResolutionAction
    notes: Optional[str] = None
    adjustment_amount: Optional[float] = None
    created_adjustment: bool = False
    resolved_at: datetime
    snapshot: Optional[dict] = None
    
    class Config:
        from_attributes = True


class ResolutionResponse(BaseModel):
    """Response after resolving."""
    
    success: bool
    resolution: dict
    match: dict


# ============================================
# Reconciliation Run
# ============================================

class ReconciliationSummary(BaseModel):
    """Summary of a reconciliation run."""
    
    total_stripe_transactions: int
    total_qbo_transactions: int
    total_stripe_amount: float
    total_qbo_amount: float
    net_difference: float
    match_rate: float
    auto_match_rate: float


class ReconciliationRun(BaseModel):
    """A reconciliation run record."""
    
    id: Optional[str] = None
    user_id: str
    period_start: datetime
    period_end: datetime
    summary: ReconciliationSummary
    
    total_matched: int
    auto_matched: int
    suggested_matched: int
    
    critical_discrepancies: int
    warning_discrepancies: int
    info_discrepancies: int
    
    unmatched_stripe: int
    unmatched_qbo: int
    
    triggered_by: Literal["manual", "scheduled", "webhook"] = "manual"
    duration_ms: Optional[int] = None
    
    created_at: Optional[datetime] = None
