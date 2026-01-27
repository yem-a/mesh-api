# app/core/normalizers.py

"""
Data normalization utilities for transactions.

Ensures consistent data format regardless of source.
"""

from datetime import date, datetime
from typing import Any
import re


def normalize_amount(amount: Any) -> float:
    """
    Normalize amount to float.
    
    Handles:
    - Integers (cents from Stripe)
    - Floats
    - Strings with currency symbols
    """
    if amount is None:
        return 0.0
    
    if isinstance(amount, (int, float)):
        return float(amount)
    
    if isinstance(amount, str):
        # Remove currency symbols and commas
        cleaned = re.sub(r'[^\d.-]', '', amount)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    
    return 0.0


def normalize_date(d: Any) -> date | None:
    """
    Normalize date to date object.
    
    Handles:
    - date objects
    - datetime objects
    - ISO strings
    - Unix timestamps
    """
    if d is None:
        return None
    
    if isinstance(d, date):
        return d
    
    if isinstance(d, datetime):
        return d.date()
    
    if isinstance(d, (int, float)):
        # Unix timestamp
        return datetime.fromtimestamp(d).date()
    
    if isinstance(d, str):
        # Try ISO format first
        try:
            return datetime.fromisoformat(d.replace('Z', '+00:00')).date()
        except ValueError:
            pass
        
        # Try common formats
        formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%d/%m/%Y',
            '%Y/%m/%d',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(d, fmt).date()
            except ValueError:
                continue
    
    return None


def normalize_string(s: str | None) -> str:
    """
    Normalize string for comparison.
    
    - Lowercase
    - Remove special characters
    - Collapse whitespace
    """
    if not s:
        return ""
    
    s = s.lower()
    s = re.sub(r'[^a-z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalize_customer_name(name: str | None) -> str:
    """
    Normalize customer name for matching.
    
    Handles:
    - Common suffixes (Inc, LLC, Corp, etc.)
    - Punctuation
    - Case
    """
    if not name:
        return ""
    
    name = name.lower()
    
    # Remove common business suffixes
    suffixes = [
        r'\s+inc\.?$',
        r'\s+llc\.?$',
        r'\s+corp\.?$',
        r'\s+corporation$',
        r'\s+ltd\.?$',
        r'\s+limited$',
        r'\s+co\.?$',
        r'\s+company$',
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)
    
    # Remove punctuation and extra whitespace
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name


def stripe_amount_to_dollars(cents: int) -> float:
    """Convert Stripe amount (cents) to dollars."""
    return cents / 100.0


def extract_customer_info(metadata: dict | None) -> tuple[str | None, str | None]:
    """
    Extract customer ID and name from metadata.
    
    Returns (customer_id, customer_name)
    """
    if not metadata:
        return None, None
    
    customer_id = None
    customer_name = None
    
    # Common field names for customer ID
    id_fields = ['customer_id', 'customerId', 'customer', 'client_id', 'clientId']
    for field in id_fields:
        if field in metadata:
            customer_id = str(metadata[field])
            break
    
    # Common field names for customer name
    name_fields = ['customer_name', 'customerName', 'name', 'client_name', 'clientName']
    for field in name_fields:
        if field in metadata:
            customer_name = str(metadata[field])
            break
    
    return customer_id, customer_name
