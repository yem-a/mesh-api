# app/routers/sync.py

"""
Sync routes for fetching transactions from Stripe and QuickBooks.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_connection, save_transactions, get_transactions
from app.integrations import stripe, quickbooks

router = APIRouter()


class SyncRequest(BaseModel):
    user_id: str
    days: int = 30


class SyncResponse(BaseModel):
    success: bool
    service: str
    transactions_synced: int
    message: str = None
    breakdown: dict = None


# ============================================
# Stripe Sync
# ============================================

@router.post("/stripe", response_model=SyncResponse)
async def sync_stripe(request: SyncRequest):
    """
    Sync transactions from Stripe.
    
    Fetches recent charges and saves to database.
    """
    # Get connection
    connection = await get_connection(request.user_id, "stripe")
    if not connection:
        raise HTTPException(
            status_code=404,
            detail="Stripe not connected. Please connect Stripe first."
        )
    
    try:
        # Fetch transactions from Stripe
        transactions = await stripe.fetch_transactions(
            access_token=connection["access_token"],
            days=request.days,
        )
        
        # Convert to dict format for database
        txn_dicts = [
            {
                "external_id": t.external_id,
                "source": t.source,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "transaction_date": t.transaction_date.isoformat(),
                "description": t.description,
                "customer_id": t.customer_id,
                "customer_name": t.customer_name,
                "metadata": t.metadata,
            }
            for t in transactions
        ]

        # Save to database
        saved_count = await save_transactions(request.user_id, txn_dicts)

        # Build breakdown by type
        breakdown = {}
        for t in transactions:
            breakdown[t.transaction_type] = breakdown.get(t.transaction_type, 0) + 1

        return SyncResponse(
            success=True,
            service="stripe",
            transactions_synced=saved_count,
            message=f"Synced {saved_count} transactions from Stripe",
            breakdown=breakdown,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync Stripe: {str(e)}"
        )


# ============================================
# QuickBooks Sync
# ============================================

@router.post("/quickbooks", response_model=SyncResponse)
async def sync_quickbooks(request: SyncRequest):
    """
    Sync transactions from QuickBooks.
    
    Fetches recent payments and saves to database.
    """
    # Get connection
    connection = await get_connection(request.user_id, "quickbooks")
    if not connection:
        raise HTTPException(
            status_code=404,
            detail="QuickBooks not connected. Please connect QuickBooks first."
        )
    
    try:
        # Fetch transactions from QuickBooks
        transactions = await quickbooks.fetch_transactions(
            access_token=connection["access_token"],
            realm_id=connection["realm_id"],
            days=request.days,
        )
        
        # Convert to dict format for database
        txn_dicts = [
            {
                "external_id": t.external_id,
                "source": t.source,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "transaction_date": t.transaction_date.isoformat(),
                "description": t.description,
                "customer_id": t.customer_id,
                "customer_name": t.customer_name,
                "metadata": t.metadata,
            }
            for t in transactions
        ]

        # Save to database
        saved_count = await save_transactions(request.user_id, txn_dicts)

        # Build breakdown by type
        breakdown = {}
        for t in transactions:
            breakdown[t.transaction_type] = breakdown.get(t.transaction_type, 0) + 1

        return SyncResponse(
            success=True,
            service="quickbooks",
            transactions_synced=saved_count,
            message=f"Synced {saved_count} transactions from QuickBooks",
            breakdown=breakdown,
        )
    
    except Exception as e:
        # Check if token expired
        if "expired" in str(e).lower():
            # Try to refresh token
            try:
                new_tokens = await quickbooks.refresh_access_token(
                    connection["refresh_token"]
                )
                # Update connection with new tokens
                from app.database import save_connection
                await save_connection(
                    user_id=request.user_id,
                    service="quickbooks",
                    access_token=new_tokens["access_token"],
                    refresh_token=new_tokens["refresh_token"],
                    realm_id=connection["realm_id"],
                )
                # Retry the sync
                return await sync_quickbooks(request)
            except Exception as refresh_error:
                raise HTTPException(
                    status_code=401,
                    detail="QuickBooks token expired. Please reconnect."
                )
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync QuickBooks: {str(e)}"
        )


# ============================================
# Sync Both
# ============================================

@router.post("/all")
async def sync_all(request: SyncRequest):
    """
    Sync transactions from both Stripe and QuickBooks.
    """
    results = {
        "user_id": request.user_id,
        "stripe": None,
        "quickbooks": None,
    }
    
    # Sync Stripe
    try:
        stripe_result = await sync_stripe(request)
        results["stripe"] = {
            "success": True,
            "transactions": stripe_result.transactions_synced,
        }
    except HTTPException as e:
        results["stripe"] = {
            "success": False,
            "error": e.detail,
        }
    
    # Sync QuickBooks
    try:
        qbo_result = await sync_quickbooks(request)
        results["quickbooks"] = {
            "success": True,
            "transactions": qbo_result.transactions_synced,
        }
    except HTTPException as e:
        results["quickbooks"] = {
            "success": False,
            "error": e.detail,
        }
    
    return results


# ============================================
# Get Synced Transactions
# ============================================

@router.get("/transactions/{user_id}")
async def get_synced_transactions(
    user_id: str,
    source: str = None,
):
    """
    Get synced transactions for a user.
    
    Optionally filter by source (stripe or quickbooks).
    """
    transactions = await get_transactions(user_id, source)
    
    return {
        "user_id": user_id,
        "source": source,
        "count": len(transactions),
        "transactions": transactions,
    }
