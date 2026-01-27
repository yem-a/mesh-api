# app/integrations/stripe.py

"""
Stripe integration for OAuth and transaction syncing.
"""

from datetime import datetime, timedelta
from typing import Optional
import stripe

from app.config import get_settings
from app.models import TransactionCreate

settings = get_settings()

# Configure Stripe
stripe.api_key = settings.stripe_secret_key


def get_oauth_url(user_id: str) -> str:
    """
    Generate Stripe Connect OAuth URL.
    
    The user_id is passed as state and returned in the callback.
    """
    params = {
        "client_id": settings.stripe_client_id,
        "state": user_id,
        "scope": "read_only",
        "response_type": "code",
        "redirect_uri": f"{settings.api_url}/auth/stripe/callback",
    }
    
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://connect.stripe.com/oauth/authorize?{query}"


async def exchange_code(code: str) -> str:
    """
    Exchange authorization code for access token.
    
    Returns the access token.
    """
    try:
        response = stripe.OAuth.token(
            grant_type="authorization_code",
            code=code,
        )
        return response.access_token
    except stripe.oauth_error.OAuthError as e:
        raise Exception(f"Stripe OAuth error: {e.description}")


async def fetch_transactions(
    access_token: str,
    days: int = 30,
) -> list[TransactionCreate]:
    """
    Fetch recent charges from Stripe.
    
    Args:
        access_token: The connected account's access token
        days: Number of days of history to fetch
    
    Returns:
        List of normalized transactions
    """
    # Use the connected account's token
    client = stripe.StripeClient(access_token)
    
    # Calculate date range
    since = datetime.now() - timedelta(days=days)
    since_timestamp = int(since.timestamp())
    
    transactions: list[TransactionCreate] = []
    
    try:
        # Fetch charges
        charges = client.charges.list(
            limit=100,
            created={"gte": since_timestamp},
        )
        
        for charge in charges.data:
            if charge.status != "succeeded":
                continue
            
            # Get customer name if available
            customer_name = None
            if charge.customer:
                try:
                    customer = client.customers.retrieve(charge.customer)
                    customer_name = customer.name or customer.email
                except:
                    pass
            
            txn = TransactionCreate(
                external_id=charge.id,
                source="stripe",
                amount=charge.amount / 100.0,  # Convert cents to dollars
                transaction_date=datetime.fromtimestamp(charge.created).date(),
                description=charge.description,
                customer_id=charge.customer,
                customer_name=customer_name,
                metadata={
                    "payment_method": charge.payment_method_details.type if charge.payment_method_details else None,
                    "receipt_url": charge.receipt_url,
                },
            )
            transactions.append(txn)
        
        return transactions
    
    except stripe.error.StripeError as e:
        raise Exception(f"Stripe API error: {str(e)}")


async def verify_connection(access_token: str) -> dict:
    """
    Verify a Stripe connection is still valid.
    
    Returns account info if valid.
    """
    try:
        client = stripe.StripeClient(access_token)
        account = client.accounts.retrieve("me")
        return {
            "valid": True,
            "account_id": account.id,
            "business_name": account.business_profile.name if account.business_profile else None,
        }
    except stripe.error.AuthenticationError:
        return {"valid": False, "error": "Token expired or invalid"}
    except stripe.error.StripeError as e:
        return {"valid": False, "error": str(e)}


async def refresh_token(refresh_token: str) -> Optional[str]:
    """
    Refresh an expired access token.
    
    Note: Stripe Connect tokens don't expire, but this is here for completeness.
    """
    # Stripe Connect access tokens don't expire
    # This would be used if we implement token rotation
    return None
