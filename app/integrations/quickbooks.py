# app/integrations/quickbooks.py

"""
QuickBooks Online integration for OAuth and transaction syncing.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
import base64
import httpx

from app.config import get_settings
from app.models import TransactionCreate

settings = get_settings()
logger = logging.getLogger(__name__)

# QuickBooks API endpoints
QBO_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_API_BASE = "https://quickbooks.api.intuit.com/v3/company"

# Sandbox vs Production
if settings.quickbooks_environment == "sandbox":
    QBO_API_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"


def get_oauth_url(user_id: str) -> str:
    """
    Generate QuickBooks OAuth URL.

    The user_id is passed as state and returned in the callback.
    """
    params = {
        "client_id": settings.quickbooks_client_id,
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": f"{settings.api_url}/auth/quickbooks/callback",
        "response_type": "code",
        "state": user_id,
    }

    return f"{QBO_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """
    Exchange authorization code for tokens.

    Returns:
        {
            "access_token": str,
            "refresh_token": str,
        }
    """
    auth = base64.b64encode(
        f"{settings.quickbooks_client_id}:{settings.quickbooks_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            QBO_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{settings.api_url}/auth/quickbooks/callback",
            },
        )

        if response.status_code != 200:
            raise Exception(f"QuickBooks OAuth error: {response.text}")

        data = response.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
        }


async def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh an expired access token.

    Returns new access_token and refresh_token.
    """
    auth = base64.b64encode(
        f"{settings.quickbooks_client_id}:{settings.quickbooks_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            QBO_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

        if response.status_code != 200:
            raise Exception(f"QuickBooks token refresh error: {response.text}")

        data = response.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
        }


# ============================================
# Pagination Helper
# ============================================

async def _paginate_qbo_query(
    access_token: str,
    realm_id: str,
    entity: str,
    date_filter: str,
    max_results: int = 100,
) -> list[dict]:
    """
    Paginate through a QuickBooks query using STARTPOSITION + MAXRESULTS.

    Returns all items across all pages.
    """
    all_items = []
    start_position = 1

    async with httpx.AsyncClient() as client:
        while True:
            query = (
                f"SELECT * FROM {entity} "
                f"WHERE TxnDate >= '{date_filter}' "
                f"STARTPOSITION {start_position} MAXRESULTS {max_results}"
            )

            response = await client.get(
                f"{QBO_API_BASE}/{realm_id}/query",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                params={"query": query},
            )

            if response.status_code == 401:
                raise Exception("QuickBooks token expired")

            if response.status_code != 200:
                raise Exception(f"QuickBooks API error ({entity}): {response.text}")

            data = response.json()
            items = data.get("QueryResponse", {}).get(entity, [])
            all_items.extend(items)

            # If fewer items returned than max, we've reached the end
            if len(items) < max_results:
                break

            start_position += max_results

            # Safety limit
            if len(all_items) > 10000:
                logger.warning(f"QBO pagination hit 10,000 item safety limit for {entity}")
                break

    return all_items


# ============================================
# Main Transaction Fetch
# ============================================

async def fetch_transactions(
    access_token: str,
    realm_id: str,
    days: int = 30,
) -> list[TransactionCreate]:
    """
    Fetch comprehensive QuickBooks transaction data.

    Fetches:
    - Payments (received payments) with full pagination
    - Credit Memos (customer credits/refunds) with full pagination
    - Refund Receipts (direct refunds) with full pagination
    - Invoices (outstanding/paid invoices) with full pagination

    Args:
        access_token: The OAuth access token
        realm_id: The QuickBooks company ID
        days: Number of days of history to fetch

    Returns:
        List of normalized transactions
    """
    since = datetime.now() - timedelta(days=days)
    date_filter = since.strftime("%Y-%m-%d")

    transactions: list[TransactionCreate] = []

    # ============================
    # 1. Fetch all Payments (paginated)
    # ============================
    all_payments = await _paginate_qbo_query(
        access_token, realm_id, "Payment", date_filter,
    )

    for payment in all_payments:
        customer_name = None
        customer_id = None
        if "CustomerRef" in payment:
            customer_id = payment["CustomerRef"].get("value")
            customer_name = payment["CustomerRef"].get("name")

        txn = TransactionCreate(
            external_id=payment["Id"],
            source="quickbooks",
            transaction_type="payment",
            amount=float(payment["TotalAmt"]),
            transaction_date=datetime.strptime(payment["TxnDate"], "%Y-%m-%d").date(),
            description=payment.get("PrivateNote", ""),
            customer_id=customer_id,
            customer_name=customer_name,
            metadata={
                "payment_method": payment.get("PaymentMethodRef", {}).get("name") if payment.get("PaymentMethodRef") else None,
                "deposit_to_account": payment.get("DepositToAccountRef", {}).get("name") if payment.get("DepositToAccountRef") else None,
            },
        )
        transactions.append(txn)

    # ============================
    # 2. Fetch all Credit Memos (paginated)
    # ============================
    all_credit_memos = await _paginate_qbo_query(
        access_token, realm_id, "CreditMemo", date_filter,
    )

    for memo in all_credit_memos:
        customer_name = None
        customer_id = None
        if "CustomerRef" in memo:
            customer_id = memo["CustomerRef"].get("value")
            customer_name = memo["CustomerRef"].get("name")

        txn = TransactionCreate(
            external_id=f"cm_{memo['Id']}",
            source="quickbooks",
            transaction_type="credit_memo",
            amount=-float(memo["TotalAmt"]),  # Negative for credits
            transaction_date=datetime.strptime(memo["TxnDate"], "%Y-%m-%d").date(),
            description=memo.get("PrivateNote", "") or "Credit Memo",
            customer_id=customer_id,
            customer_name=customer_name,
            metadata={
                "remaining_credit": float(memo.get("RemainingCredit", 0)),
                "doc_number": memo.get("DocNumber"),
            },
        )
        transactions.append(txn)

    # ============================
    # 3. Fetch all Refund Receipts (paginated)
    # ============================
    all_refund_receipts = await _paginate_qbo_query(
        access_token, realm_id, "RefundReceipt", date_filter,
    )

    for refund in all_refund_receipts:
        customer_name = None
        customer_id = None
        if "CustomerRef" in refund:
            customer_id = refund["CustomerRef"].get("value")
            customer_name = refund["CustomerRef"].get("name")

        txn = TransactionCreate(
            external_id=f"rr_{refund['Id']}",
            source="quickbooks",
            transaction_type="refund",
            amount=-float(refund["TotalAmt"]),  # Negative for refunds
            transaction_date=datetime.strptime(refund["TxnDate"], "%Y-%m-%d").date(),
            description=refund.get("PrivateNote", "") or "Refund Receipt",
            customer_id=customer_id,
            customer_name=customer_name,
            metadata={
                "payment_method": refund.get("PaymentMethodRef", {}).get("name") if refund.get("PaymentMethodRef") else None,
                "deposit_to_account": refund.get("DepositToAccountRef", {}).get("name") if refund.get("DepositToAccountRef") else None,
                "doc_number": refund.get("DocNumber"),
            },
        )
        transactions.append(txn)

    # ============================
    # 4. Fetch all Invoices (paginated)
    # ============================
    all_invoices = await _paginate_qbo_query(
        access_token, realm_id, "Invoice", date_filter,
    )

    for invoice in all_invoices:
        customer_name = None
        customer_id = None
        if "CustomerRef" in invoice:
            customer_id = invoice["CustomerRef"].get("value")
            customer_name = invoice["CustomerRef"].get("name")

        txn = TransactionCreate(
            external_id=f"inv_{invoice['Id']}",
            source="quickbooks",
            transaction_type="invoice",
            amount=float(invoice["TotalAmt"]),
            transaction_date=datetime.strptime(invoice["TxnDate"], "%Y-%m-%d").date(),
            description=invoice.get("CustomerMemo", {}).get("value", "") if invoice.get("CustomerMemo") else "",
            customer_id=customer_id,
            customer_name=customer_name,
            metadata={
                "invoice_number": invoice.get("DocNumber"),
                "balance": float(invoice.get("Balance", 0)),
                "due_date": invoice.get("DueDate"),
            },
        )
        transactions.append(txn)

    # Log summary
    counts = {}
    for t in transactions:
        counts[t.transaction_type] = counts.get(t.transaction_type, 0) + 1
    logger.info(
        f"Fetched from QuickBooks: "
        + ", ".join(f"{count} {ttype}s" for ttype, count in counts.items())
    )

    return transactions


async def verify_connection(access_token: str, realm_id: str) -> dict:
    """
    Verify a QuickBooks connection is still valid.

    Returns company info if valid.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{QBO_API_BASE}/{realm_id}/companyinfo/{realm_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

        if response.status_code == 401:
            return {"valid": False, "error": "Token expired"}

        if response.status_code != 200:
            return {"valid": False, "error": response.text}

        data = response.json()
        company = data.get("CompanyInfo", {})

        return {
            "valid": True,
            "company_id": realm_id,
            "company_name": company.get("CompanyName"),
        }
