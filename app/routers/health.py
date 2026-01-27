# app/routers/health.py

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "mesh-api",
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check - could verify DB connection etc."""
    # TODO: Add actual readiness checks (DB, external services)
    return {
        "status": "ready",
        "checks": {
            "database": "ok",
            "stripe": "ok",
            "quickbooks": "ok",
        }
    }
