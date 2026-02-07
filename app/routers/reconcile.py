# app/routers/reconcile.py

"""
Reconciliation routes.

The main endpoint that runs the matching engine.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.database import (
    get_transactions,
    save_matches,
    save_reconciliation_run,
    get_reconciliation_history,
)
from app.core.matching import reconcile
from app.core.ai_assist import enhance_matches_with_ai
from app.dependencies import get_current_user
from app.models import TransactionCreate
from app.config import get_settings

settings = get_settings()
router = APIRouter()


class ReconcileRequest(BaseModel):
    enhance_with_ai: bool = True
    persist: bool = True


class ReconcileResponse(BaseModel):
    success: bool
    summary: dict
    matched_count: int
    unmatched_stripe_count: int
    unmatched_qbo_count: int
    discrepancies: dict
    duration_ms: int


# ============================================
# Main Reconciliation Endpoint
# ============================================

@router.post("/reconcile", response_model=ReconcileResponse)
async def run_reconciliation(request: ReconcileRequest, user_id: str = Depends(get_current_user)):
    """
    Run reconciliation for the authenticated user.

    1. Fetches synced transactions from database
    2. Runs the matching engine
    3. Optionally enhances with AI explanations
    4. Saves results to database
    """
    start_time = datetime.now()

    # Get transactions from database
    stripe_txns = await get_transactions(user_id, "stripe")
    qbo_txns = await get_transactions(user_id, "quickbooks")

    if not stripe_txns and not qbo_txns:
        raise HTTPException(
            status_code=400,
            detail="No transactions found. Please sync Stripe and QuickBooks first."
        )

    # Convert to TransactionCreate objects
    stripe_transactions = [
        TransactionCreate(
            external_id=t["external_id"],
            source="stripe",
            transaction_type=t.get("transaction_type", "charge"),
            amount=float(t["amount"]),
            transaction_date=t["transaction_date"],
            description=t.get("description"),
            customer_id=t.get("customer_id"),
            customer_name=t.get("customer_name"),
            metadata=t.get("metadata", {}),
        )
        for t in stripe_txns
    ]

    qbo_transactions = [
        TransactionCreate(
            external_id=t["external_id"],
            source="quickbooks",
            transaction_type=t.get("transaction_type", "payment"),
            amount=float(t["amount"]),
            transaction_date=t["transaction_date"],
            description=t.get("description"),
            customer_id=t.get("customer_id"),
            customer_name=t.get("customer_name"),
            metadata=t.get("metadata", {}),
        )
        for t in qbo_txns
    ]

    # Run matching engine
    result = reconcile(stripe_transactions, qbo_transactions, user_id)

    # Enhance with AI if requested
    if request.enhance_with_ai and settings.enable_ai_explanations:
        try:
            result.matched = await enhance_matches_with_ai(
                result.matched,
                user_id,
            )
        except Exception as e:
            print(f"AI enhancement failed: {e}")
            # Continue without AI - not a critical failure

    # Persist results if requested
    if request.persist:
        try:
            # Save matches
            match_dicts = [m.model_dump() for m in result.matched]
            await save_matches(user_id, match_dicts)

            # Save reconciliation run
            run = {
                "user_id": user_id,
                "period_start": result.period_start.isoformat() if result.period_start else None,
                "period_end": result.period_end.isoformat() if result.period_end else None,
                "total_stripe_transactions": result.summary.total_stripe_transactions,
                "total_qbo_transactions": result.summary.total_qbo_transactions,
                "total_stripe_amount": result.summary.total_stripe_amount,
                "total_qbo_amount": result.summary.total_qbo_amount,
                "net_difference": result.summary.net_difference,
                "total_matched": len(result.matched),
                "auto_matched": len([m for m in result.matched if m.status == "auto_matched"]),
                "suggested_matched": len([m for m in result.matched if m.status == "suggested"]),
                "match_rate": result.summary.match_rate,
                "auto_match_rate": result.summary.auto_match_rate,
                "critical_discrepancies": len(result.discrepancies["critical"]),
                "warning_discrepancies": len(result.discrepancies["warnings"]),
                "info_discrepancies": len(result.discrepancies["info"]),
                "unmatched_stripe": len(result.unmatched_stripe),
                "unmatched_qbo": len(result.unmatched_qbo),
                "triggered_by": "manual",
                "duration_ms": result.duration_ms,
            }
            await save_reconciliation_run(run)
        except Exception as e:
            print(f"Failed to persist results: {e}")
            # Continue - persistence failure shouldn't fail the whole request

    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    return ReconcileResponse(
        success=True,
        summary=result.summary.model_dump(),
        matched_count=len(result.matched),
        unmatched_stripe_count=len(result.unmatched_stripe),
        unmatched_qbo_count=len(result.unmatched_qbo),
        discrepancies={
            "critical": len(result.discrepancies["critical"]),
            "warnings": len(result.discrepancies["warnings"]),
            "info": len(result.discrepancies["info"]),
        },
        duration_ms=duration_ms,
    )


# ============================================
# Get Reconciliation Results
# ============================================

@router.get("/reconcile/results")
async def get_reconciliation_results(user_id: str = Depends(get_current_user)):
    """
    Get the latest reconciliation results for the authenticated user.
    """
    from app.database import get_matches

    matches, total = await get_matches(user_id, limit=100)

    # Categorize
    discrepancies = {
        "critical": [],
        "warnings": [],
        "info": [],
    }

    for match in matches:
        if match.get("has_discrepancy"):
            severity = match.get("discrepancy_severity", "info")
            if severity == "critical":
                discrepancies["critical"].append(match)
            elif severity == "warning":
                discrepancies["warnings"].append(match)
            else:
                discrepancies["info"].append(match)

    return {
        "user_id": user_id,
        "total_matches": total,
        "matches": matches,
        "discrepancies": {
            "critical": len(discrepancies["critical"]),
            "warnings": len(discrepancies["warnings"]),
            "info": len(discrepancies["info"]),
            "items": discrepancies,
        },
    }


# ============================================
# Reconciliation History (for trend chart)
# ============================================

@router.get("/reconcile/history")
async def get_reconciliation_history_endpoint(
    user_id: str = Depends(get_current_user),
    limit: int = Query(30, ge=1, le=90),
):
    """
    Get reconciliation run history for the authenticated user.

    Returns historical runs for charting reconciliation trends.
    """
    runs = await get_reconciliation_history(user_id, limit)

    return {
        "user_id": user_id,
        "runs": runs,
        "count": len(runs),
    }
