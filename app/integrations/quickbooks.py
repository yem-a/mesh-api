# app/integrations/quickbooks.py

"""
QuickBooks Online integration for OAuth and payment syncing.
"""

from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
import base64
import httpx

from app.config import get_settings
from app.models import TransactionCreate

settings = get_settings()

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
            "realm_id": str (company ID)
        }
    """
    # Build authorization header
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


async def fetch_transactions(
    access_token: str,
    realm_id: str,
    days: int = 30,
) -> list[TransactionCreate]:
    """
    Fetch recent payments from QuickBooks.
    
    Args:
        access_token: The OAuth access token
        realm_id: The QuickBooks company ID
        days: Number of days of history to fetch
    
    Returns:
        List of normalized transactions
    """
    # Calculate date range
    since = datetime.now() - timedelta(days=days)
    date_filter = since.strftime("%Y-%m-%d")
    
    # Query for payments
    query = f"SELECT * FROM Payment WHERE TxnDate >= '{date_filter}' MAXRESULTS 100"
    
    async with httpx.AsyncClient() as client:
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
            raise Exception(f"QuickBooks API error: {response.text}")
        
        data = response.json()
        payments = data.get("QueryResponse", {}).get("Payment", [])
        
        transactions: list[TransactionCreate] = []
        
        for payment in payments:
            # Get customer name
            customer_name = None
            customer_id = None
            if "CustomerRef" in payment:
                customer_id = payment["CustomerRef"].get("value")
                customer_name = payment["CustomerRef"].get("name")
            
            txn = TransactionCreate(
                external_id=payment["Id"],
                source="quickbooks",
                amount=float(payment["TotalAmt"]),
                transaction_date=datetime.strptime(payment["TxnDate"], "%Y-%m-%d").date(),
                description=payment.get("PrivateNote", ""),
                customer_id=customer_id,
                customer_name=customer_name,
                metadata={
                    "payment_method": payment.get("PaymentMethodRef", {}).get("name"),
                    "deposit_to_account": payment.get("DepositToAccountRef", {}).get("name"),
                },
            )
            transactions.append(txn)
        
        return transactions


async def fetch_invoices(
    access_token: str,
    realm_id: str,
    days: int = 30,
) -> list[TransactionCreate]:
    """
    Fetch recent invoices from QuickBooks.
    
    Useful for matching against Stripe charges that haven't been
    recorded as payments yet.
    """
    since = datetime.now() - timedelta(days=days)
    date_filter = since.strftime("%Y-%m-%d")
    
    query = f"SELECT * FROM Invoice WHERE TxnDate >= '{date_filter}' MAXRESULTS 100"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{QBO_API_BASE}/{realm_id}/query",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={"query": query},
        )
        
        if response.status_code != 200:
            raise Exception(f"QuickBooks API error: {response.text}")
        
        data = response.json()
        invoices = data.get("QueryResponse", {}).get("Invoice", [])
        
        transactions: list[TransactionCreate] = []
        
        for invoice in invoices:
            customer_name = None
            customer_id = None
            if "CustomerRef" in invoice:
                customer_id = invoice["CustomerRef"].get("value")
                customer_name = invoice["CustomerRef"].get("name")
            
            txn = TransactionCreate(
                external_id=f"inv_{invoice['Id']}",
                source="quickbooks",
                amount=float(invoice["TotalAmt"]),
                transaction_date=datetime.strptime(invoice["TxnDate"], "%Y-%m-%d").date(),
                description=invoice.get("CustomerMemo", {}).get("value", ""),
                customer_id=customer_id,
                customer_name=customer_name,
                metadata={
                    "invoice_number": invoice.get("DocNumber"),
                    "balance": float(invoice.get("Balance", 0)),
                },
            )
            transactions.append(txn)
        
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
