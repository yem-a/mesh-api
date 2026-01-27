# app/config.py

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # App
    app_name: str = "Mesh API"
    app_env: str = "development"
    debug: bool = True
    frontend_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    
    # Stripe
    stripe_client_id: str
    stripe_secret_key: str
    
    # QuickBooks
    quickbooks_client_id: str
    quickbooks_client_secret: str
    quickbooks_environment: str = "sandbox"  # or "production"
    
    # Anthropic (Claude)
    anthropic_api_key: str
    
    # Feature flags
    enable_ai_explanations: bool = True
    enable_ai_suggestions: bool = True
    
    # Matching config
    auto_match_threshold: int = 85
    date_tolerance_days: int = 3
    stripe_fee_percent: float = 2.9
    stripe_fee_fixed: float = 0.30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
