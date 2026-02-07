# app/routers/auth.py

"""
OAuth authentication routes for Stripe and QuickBooks.

Handles the OAuth flow:
1. /auth/stripe/connect - Returns Stripe OAuth URL (JWT protected)
2. /auth/stripe/callback - Handles Stripe callback (public - OAuth redirect)
3. /auth/quickbooks/connect - Returns QuickBooks OAuth URL (JWT protected)
4. /auth/quickbooks/callback - Handles QuickBooks callback (public - OAuth redirect)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.database import save_connection, get_connection, delete_connection
from app.dependencies import get_current_user
from app.integrations import stripe, quickbooks

settings = get_settings()
router = APIRouter()


# ============================================
# Stripe OAuth
# ============================================

@router.get("/stripe/connect")
async def stripe_connect(user_id: str = Depends(get_current_user)):
    """
    Initiate Stripe OAuth flow.

    Returns the OAuth URL for the frontend to redirect to.
    """
    oauth_url = stripe.get_oauth_url(user_id)
    return {"url": oauth_url}


@router.get("/stripe/callback")
async def stripe_callback(
    code: str = Query(None),
    state: str = Query(None),  # This is the user_id
    error: str = Query(None),
    error_description: str = Query(None),
):
    """
    Handle Stripe OAuth callback.

    Exchanges code for access token and saves to database.
    This endpoint is public (called by Stripe redirect, no JWT available).
    """
    # Check for errors
    if error:
        error_msg = error_description or error
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?error={error_msg}"
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?error=missing_code_or_state"
        )

    user_id = state

    try:
        # Exchange code for token
        access_token = await stripe.exchange_code(code)

        # Save connection
        await save_connection(
            user_id=user_id,
            service="stripe",
            access_token=access_token,
        )

        # Redirect back to frontend with success
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?stripe=connected"
        )

    except Exception as e:
        print(f"Stripe callback error: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?error=stripe_connection_failed"
        )


# ============================================
# QuickBooks OAuth
# ============================================

@router.get("/quickbooks/connect")
async def quickbooks_connect(user_id: str = Depends(get_current_user)):
    """
    Initiate QuickBooks OAuth flow.

    Returns the OAuth URL for the frontend to redirect to.
    """
    oauth_url = quickbooks.get_oauth_url(user_id)
    return {"url": oauth_url}


@router.get("/quickbooks/callback")
async def quickbooks_callback(
    code: str = Query(None),
    state: str = Query(None),  # This is the user_id
    realmId: str = Query(None),  # QuickBooks company ID
    error: str = Query(None),
):
    """
    Handle QuickBooks OAuth callback.

    Exchanges code for tokens and saves to database.
    This endpoint is public (called by QuickBooks redirect, no JWT available).
    """
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?error={error}"
        )

    if not code or not state or not realmId:
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?error=missing_parameters"
        )

    user_id = state

    try:
        # Exchange code for tokens
        tokens = await quickbooks.exchange_code(code)

        # Save connection
        await save_connection(
            user_id=user_id,
            service="quickbooks",
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            realm_id=realmId,
        )

        # Redirect back to frontend with success
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?quickbooks=connected"
        )

    except Exception as e:
        print(f"QuickBooks callback error: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/signup?error=quickbooks_connection_failed"
        )


# ============================================
# Connection Status
# ============================================

@router.get("/status")
async def connection_status(user_id: str = Depends(get_current_user)):
    """
    Get connection status for the authenticated user.
    """
    stripe_conn = await get_connection(user_id, "stripe")
    qbo_conn = await get_connection(user_id, "quickbooks")

    return {
        "user_id": user_id,
        "stripe": {
            "connected": stripe_conn is not None,
            "status": stripe_conn.get("status") if stripe_conn else None,
            "connected_at": stripe_conn.get("connected_at") if stripe_conn else None,
        },
        "quickbooks": {
            "connected": qbo_conn is not None,
            "status": qbo_conn.get("status") if qbo_conn else None,
            "connected_at": qbo_conn.get("connected_at") if qbo_conn else None,
            "realm_id": qbo_conn.get("realm_id") if qbo_conn else None,
        },
    }


@router.post("/disconnect/{service}")
async def disconnect_service(service: str, user_id: str = Depends(get_current_user)):
    """
    Disconnect a service for the authenticated user.
    """
    if service not in ["stripe", "quickbooks"]:
        raise HTTPException(status_code=400, detail="Invalid service")

    deleted = await delete_connection(user_id, service)

    return {
        "success": True,
        "deleted": deleted,
        "message": f"{service} disconnected",
    }
