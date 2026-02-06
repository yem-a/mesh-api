# app/integrations/stripe.py

"""
Stripe integration for OAuth and transaction syncing.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import stripe

from app.config import get_settings
from app.models import TransactionCreate

settings = get_settings()
logger = logging.getLogger(__name__)

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
        "scope": "read_write",
        "response_type": "code",
        "redirect_uri": f"{settings.api_url}/auth/stripe/callback",
        "stripe_landing": "login",
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


# ============================================
# Pagination & Customer Resolution Helpers
# ============================================

def _paginate_stripe_list(resource_method, **params) -> list:
    """
    Paginate through a Stripe list endpoint using starting_after cursor.

    Returns all items across all pages.
    """
    all_items = []
    has_more = True
    starting_after = None

    while has_more:
        if starting_after:
            params["starting_after"] = starting_after

        response = resource_method(**params)

        items = response.data
        all_items.extend(items)
        has_more = response.has_more

        if items:
            starting_after = items[-1].id
        else:
            break

        # Safety limit
        if len(all_items) > 10000:
            logger.warning("Stripe pagination hit 10,000 item safety limit")
            break

    return all_items


def _resolve_customer_names(client, customer_ids: set) -> dict:
    """
    Batch-resolve customer display names from Stripe.

    Returns {customer_id: display_name}.
    """
    cache = {}
    for cid in customer_ids:
        if not cid or cid in cache:
            continue
        try:
            customer = client.customers.retrieve(cid)
            cache[cid] = customer.name or customer.email or cid
        except Exception:
            cache[cid] = cid
    return cache


# ============================================
# Main Transaction Fetch
# ============================================

async def fetch_transactions(
    access_token: str,
    days: int = 30,
) -> list[TransactionCreate]:
    """
    Fetch comprehensive Stripe transaction data.

    Fetches:
    - Charges (succeeded) with full pagination
    - Refunds (succeeded) with full pagination
    - Actual fee data from balance transactions

    Args:
        access_token: The connected account's access token
        days: Number of days of history to fetch

    Returns:
        List of normalized transactions (charges + refunds)
    """
    client = stripe.StripeClient(access_token)

    since = datetime.now() - timedelta(days=days)
    since_timestamp = int(since.timestamp())

    transactions: list[TransactionCreate] = []

    try:
        # ============================
        # 1. Fetch all charges (paginated)
        # ============================
        all_charges = _paginate_stripe_list(
            client.charges.list,
            limit=100,
            created={"gte": since_timestamp},
        )

        # Batch-resolve customer names
        customer_ids = {c.customer for c in all_charges if c.customer}
        customer_names = _resolve_customer_names(client, customer_ids)

        for charge in all_charges:
            if charge.status != "succeeded":
                continue

            customer_name = customer_names.get(charge.customer) if charge.customer else None

            # Get actual fee from balance_transaction if available
            fee_amount = None
            net_amount = None
            if charge.balance_transaction:
                try:
                    bal_txn = client.balance_transactions.retrieve(charge.balance_transaction)
                    fee_amount = bal_txn.fee / 100.0
                    net_amount = bal_txn.net / 100.0
                except Exception:
                    pass

            txn = TransactionCreate(
                external_id=charge.id,
                source="stripe",
                transaction_type="charge",
                amount=charge.amount / 100.0,
                transaction_date=datetime.fromtimestamp(charge.created).date(),
                description=charge.description or "Stripe charge",
                customer_id=charge.customer,
                customer_name=customer_name,
                metadata={
                    "payment_method": charge.payment_method_details.type if charge.payment_method_details else None,
                    "receipt_url": charge.receipt_url,
                    "fee_amount": fee_amount,
                    "net_amount": net_amount,
                    "currency": charge.currency,
                },
            )
            transactions.append(txn)

        # ============================
        # 2. Fetch all refunds (paginated)
        # ============================
        all_refunds = _paginate_stripe_list(
            client.refunds.list,
            limit=100,
            created={"gte": since_timestamp},
        )

        # Build a lookup from charge ID to charge for resolving refund customers
        charge_lookup = {c.id: c for c in all_charges}

        for refund in all_refunds:
            if refund.status != "succeeded":
                continue

            # Resolve customer from the original charge
            customer_id = None
            customer_name = None
            if refund.charge and refund.charge in charge_lookup:
                original_charge = charge_lookup[refund.charge]
                customer_id = original_charge.customer
                customer_name = customer_names.get(original_charge.customer) if original_charge.customer else None

            txn = TransactionCreate(
                external_id=refund.id,
                source="stripe",
                transaction_type="refund",
                amount=-(refund.amount / 100.0),  # Negative for refunds
                transaction_date=datetime.fromtimestamp(refund.created).date(),
                description=f"Refund: {refund.reason or 'No reason provided'}",
                customer_id=customer_id,
                customer_name=customer_name,
                metadata={
                    "original_charge_id": refund.charge,
                    "refund_reason": refund.reason,
                    "currency": refund.currency,
                },
            )
            transactions.append(txn)

        charge_count = len([t for t in transactions if t.transaction_type == "charge"])
        refund_count = len([t for t in transactions if t.transaction_type == "refund"])
        logger.info(f"Fetched {charge_count} charges and {refund_count} refunds from Stripe")

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
