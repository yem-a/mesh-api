# app/routers/matches.py

"""
Match management routes.

CRUD operations for matches and resolution handling.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.database import (
    get_matches,
    get_match,
    update_match,
    save_resolution,
    get_user_resolutions,
)
from app.core.ai_assist import get_ai_suggestion, explain_match
from app.dependencies import get_current_user
from app.models import ResolutionAction

router = APIRouter()


# ============================================
# Request/Response Models
# ============================================

class ResolveRequest(BaseModel):
    action: ResolutionAction
    notes: Optional[str] = None
    adjustment_amount: Optional[float] = None


class MatchesResponse(BaseModel):
    success: bool
    matches: list
    pagination: dict


# ============================================
# Get Matches
# ============================================

@router.get("")
async def list_matches(
    user_id: str = Depends(get_current_user),
    status: Optional[str] = Query(None, description="Filter by status"),
    has_discrepancy: Optional[bool] = Query(None, description="Filter by discrepancy"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    List matches for the authenticated user with optional filters.
    """
    matches, total = await get_matches(
        user_id=user_id,
        status=status,
        has_discrepancy=has_discrepancy,
        severity=severity,
        limit=limit,
        offset=offset,
    )

    return {
        "success": True,
        "matches": matches,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    }


@router.get("/discrepancies")
async def list_discrepancies(
    user_id: str = Depends(get_current_user),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    List matches with discrepancies.
    """
    matches, total = await get_matches(
        user_id=user_id,
        has_discrepancy=True,
        severity=severity,
        limit=limit,
        offset=offset,
    )

    # Calculate summary
    all_matches, _ = await get_matches(user_id=user_id, has_discrepancy=True, limit=1000)
    summary = {"critical": 0, "warning": 0, "info": 0, "total": 0}
    for m in all_matches:
        sev = m.get("discrepancy_severity", "info")
        summary[sev] = summary.get(sev, 0) + 1
        summary["total"] += 1

    return {
        "success": True,
        "discrepancies": matches,
        "summary": summary,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    }


# ============================================
# Resolution History
# ============================================

@router.get("/resolutions")
async def get_resolution_history(
    user_id: str = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Get resolution history for the authenticated user.
    """
    resolutions = await get_user_resolutions(user_id, limit)

    return {
        "success": True,
        "user_id": user_id,
        "resolutions": resolutions,
        "count": len(resolutions),
    }


# ============================================
# Get Single Match
# ============================================

@router.get("/{match_id}")
async def get_single_match(
    match_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Get a single match by ID.
    """
    match = await get_match(match_id, user_id)

    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    return {
        "success": True,
        "match": match,
    }


# ============================================
# Resolve Match
# ============================================

@router.post("/{match_id}/resolve")
async def resolve_match(
    match_id: str,
    request: ResolveRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Resolve a match discrepancy.

    Records the user's action and updates match status.
    """
    # Validate action
    valid_actions = [
        "mark_as_expected",
        "flag_for_review",
        "create_qbo_entry",
        "ignore_permanently",
        "manual_match",
        "split_transaction",
        "adjust_amount",
    ]

    if request.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        )

    # Get the match
    match = await get_match(match_id, user_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Create resolution record
    resolution = {
        "match_id": match_id,
        "user_id": user_id,
        "action": request.action,
        "notes": request.notes,
        "adjustment_amount": request.adjustment_amount,
        "created_adjustment": request.action == "adjust_amount" and request.adjustment_amount is not None,
        "snapshot": match,
    }

    saved_resolution = await save_resolution(resolution)

    # Determine new status
    status_map = {
        "mark_as_expected": "resolved",
        "flag_for_review": "suggested",
        "create_qbo_entry": "resolved",
        "ignore_permanently": "resolved",
        "manual_match": "confirmed",
        "split_transaction": "resolved",
        "adjust_amount": "resolved",
    }
    new_status = status_map.get(request.action, "resolved")

    # Update match status
    await update_match(match_id, {"status": new_status})

    return {
        "success": True,
        "resolution": {
            "id": saved_resolution.get("id"),
            "action": request.action,
            "resolved_at": datetime.now().isoformat(),
        },
        "match": {
            "id": match_id,
            "new_status": new_status,
        },
    }


# ============================================
# AI Suggestions
# ============================================

@router.get("/{match_id}/suggestion")
async def get_suggestion(
    match_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Get AI suggestion for resolving a match.
    """
    from app.models import MatchDB

    match_data = await get_match(match_id, user_id)
    if not match_data:
        raise HTTPException(status_code=404, detail="Match not found")

    # Convert to MatchDB for AI processing
    match = MatchDB(**match_data)

    suggestion = await get_ai_suggestion(match, user_id)

    return {
        "success": True,
        "match_id": match_id,
        "suggestion": suggestion,
    }


@router.get("/{match_id}/explain")
async def get_explanation(
    match_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Get AI explanation for a match.
    """
    from app.models import MatchDB

    match_data = await get_match(match_id, user_id)
    if not match_data:
        raise HTTPException(status_code=404, detail="Match not found")

    match = MatchDB(**match_data)
    explanation = await explain_match(match)

    return {
        "success": True,
        "match_id": match_id,
        "explanation": explanation,
    }
