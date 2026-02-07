# app/database.py

from supabase import create_client, Client
from app.config import get_settings

settings = get_settings()

# Public client (respects RLS)
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_anon_key
)

# Admin client (bypasses RLS - use carefully)
supabase_admin: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_role_key
)


# ============================================
# Database helper functions
# ============================================

async def get_user_connections(user_id: str) -> dict:
    """Get all connections for a user."""
    response = supabase_admin.table("connections").select("*").eq("user_id", user_id).execute()
    
    connections = {"stripe": None, "quickbooks": None}
    for conn in response.data:
        connections[conn["service"]] = conn
    return connections


async def save_connection(
    user_id: str,
    service: str,
    access_token: str,
    refresh_token: str = None,
    realm_id: str = None
) -> dict:
    """Save or update a connection."""
    data = {
        "user_id": user_id,
        "service": service,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "realm_id": realm_id,
        "status": "active",
    }
    
    response = supabase_admin.table("connections").upsert(
        data,
        on_conflict="user_id,service"
    ).execute()
    
    return response.data[0] if response.data else None


async def get_connection(user_id: str, service: str) -> dict | None:
    """Get a specific connection."""
    response = supabase_admin.table("connections").select("*").eq("user_id", user_id).eq("service", service).execute()
    return response.data[0] if response.data else None


async def delete_connection(user_id: str, service: str) -> bool:
    """Delete a connection (disconnect a service)."""
    response = supabase_admin.table("connections").delete().eq("user_id", user_id).eq("service", service).execute()
    return len(response.data) > 0 if response.data else False


async def save_transactions(user_id: str, transactions: list[dict]) -> int:
    """Save transactions to database."""
    if not transactions:
        return 0
    
    # Add user_id to each transaction
    for txn in transactions:
        txn["user_id"] = user_id
    
    response = supabase_admin.table("transactions").upsert(
        transactions,
        on_conflict="user_id,source,external_id"
    ).execute()
    
    return len(response.data) if response.data else 0


async def get_transactions(user_id: str, source: str = None, transaction_type: str = None, customer_id: str = None) -> list[dict]:
    """Get transactions for a user."""
    query = supabase_admin.table("transactions").select("*").eq("user_id", user_id)

    if source:
        query = query.eq("source", source)
    if transaction_type:
        query = query.eq("transaction_type", transaction_type)
    if customer_id:
        query = query.eq("customer_id", customer_id)

    response = query.order("transaction_date", desc=True).execute()
    return response.data


async def save_matches(user_id: str, matches: list[dict]) -> int:
    """Save matches to database."""
    if not matches:
        return 0
    
    for match in matches:
        match["user_id"] = user_id
    
    response = supabase_admin.table("matches").upsert(
        matches,
        on_conflict="user_id,stripe_external_id,qbo_external_id"
    ).execute()
    
    return len(response.data) if response.data else 0


async def get_matches(
    user_id: str,
    status: str = None,
    has_discrepancy: bool = None,
    severity: str = None,
    limit: int = 50,
    offset: int = 0
) -> tuple[list[dict], int]:
    """Get matches with filters."""
    query = supabase_admin.table("matches").select("*", count="exact").eq("user_id", user_id)
    
    if status:
        query = query.eq("status", status)
    if has_discrepancy is not None:
        query = query.eq("has_discrepancy", has_discrepancy)
    if severity:
        query = query.eq("discrepancy_severity", severity)
    
    response = query.order("matched_at", desc=True).range(offset, offset + limit - 1).execute()
    
    return response.data, response.count


async def get_match(match_id: str, user_id: str) -> dict | None:
    """Get a single match."""
    response = supabase_admin.table("matches").select("*").eq("id", match_id).eq("user_id", user_id).execute()
    return response.data[0] if response.data else None


async def update_match(match_id: str, updates: dict) -> dict | None:
    """Update a match."""
    response = supabase_admin.table("matches").update(updates).eq("id", match_id).execute()
    return response.data[0] if response.data else None


async def save_resolution(resolution: dict) -> dict:
    """Save a resolution."""
    response = supabase_admin.table("resolutions").insert(resolution).execute()
    return response.data[0] if response.data else None


async def get_user_resolutions(user_id: str, limit: int = 50) -> list[dict]:
    """Get user's resolution history."""
    response = supabase_admin.table("resolutions").select("*").eq("user_id", user_id).order("resolved_at", desc=True).limit(limit).execute()
    return response.data


async def save_reconciliation_run(run: dict) -> dict:
    """Save a reconciliation run."""
    response = supabase_admin.table("reconciliation_runs").insert(run).execute()
    return response.data[0] if response.data else None


async def get_reconciliation_history(user_id: str, limit: int = 30) -> list[dict]:
    """Get reconciliation run history for a user."""
    response = (
        supabase_admin.table("reconciliation_runs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data
