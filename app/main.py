# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, sync, reconcile, matches, health

settings = get_settings()

# ============================================
# Create FastAPI app
# ============================================

app = FastAPI(
    title=settings.app_name,
    description="Reconciliation engine for Stripe ↔ QuickBooks",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# ============================================
# CORS middleware
# ============================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "https://trymesh.co",
        "https://www.trymesh.co",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# Include routers
# ============================================

app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(sync.router, prefix="/sync", tags=["Sync"])
app.include_router(reconcile.router, tags=["Reconciliation"])
app.include_router(matches.router, prefix="/matches", tags=["Matches"])

# ============================================
# Root endpoint
# ============================================

@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if settings.debug else None,
    }
