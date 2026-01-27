# Mesh API

Python backend for Mesh - the automated reconciliation engine for Stripe ↔ QuickBooks.

## Architecture

```
mesh-api/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Environment configuration
│   ├── database.py          # Supabase client
│   │
│   ├── routers/             # API endpoints
│   │   ├── auth.py          # OAuth flows (Stripe, QuickBooks)
│   │   ├── sync.py          # Transaction syncing
│   │   ├── reconcile.py     # Main matching endpoint
│   │   ├── matches.py       # Match CRUD & resolution
│   │   └── health.py        # Health checks
│   │
│   ├── integrations/        # External services
│   │   ├── stripe.py        # Stripe OAuth + API
│   │   ├── quickbooks.py    # QuickBooks OAuth + API
│   │   └── claude.py        # AI explanations
│   │
│   ├── core/                # THE MOAT
│   │   ├── matching.py      # Main matching algorithm
│   │   ├── confidence.py    # Scoring system
│   │   ├── classification.py # Discrepancy detection
│   │   ├── ai_assist.py     # AI enhancements
│   │   └── normalizers.py   # Data cleaning
│   │
│   └── models/              # Pydantic schemas
│       ├── transaction.py
│       ├── match.py
│       └── resolution.py
│
├── tests/
├── requirements.txt
├── railway.toml             # Deployment config
└── .env.example
```

## Quick Start

### 1. Setup

```bash
# Clone and enter directory
cd mesh-api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your actual values
```

### 2. Environment Variables

Required in `.env`:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
STRIPE_CLIENT_ID=ca_xxxxx
STRIPE_SECRET_KEY=sk_test_xxxxx
QUICKBOOKS_CLIENT_ID=your-client-id
QUICKBOOKS_CLIENT_SECRET=your-client-secret
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

### 3. Run Locally

```bash
uvicorn app.main:app --reload
```

API will be available at `http://localhost:8000`

### 4. Test

```bash
# Health check
curl http://localhost:8000/health

# API docs
open http://localhost:8000/docs
```

## API Endpoints

### Authentication
- `GET /auth/stripe/connect?user_id=xxx` - Start Stripe OAuth
- `GET /auth/quickbooks/connect?user_id=xxx` - Start QuickBooks OAuth
- `GET /auth/status/{user_id}` - Check connection status

### Sync
- `POST /sync/stripe` - Sync Stripe transactions
- `POST /sync/quickbooks` - Sync QuickBooks transactions
- `POST /sync/all` - Sync both

### Reconciliation
- `POST /reconcile` - Run matching engine
- `GET /reconcile/{user_id}/results` - Get latest results

### Matches
- `GET /matches?user_id=xxx` - List matches
- `GET /matches/discrepancies?user_id=xxx` - List discrepancies
- `POST /matches/{match_id}/resolve` - Resolve a discrepancy
- `GET /matches/{match_id}/suggestion` - Get AI suggestion

## Deployment

### Railway

1. Connect GitHub repo to Railway
2. Add environment variables in Railway dashboard
3. Deploy

The `railway.toml` handles the rest.

### Manual

```bash
# Production server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Development

### Adding New Integrations

1. Create integration in `app/integrations/`
2. Add OAuth routes in `app/routers/auth.py`
3. Add sync route in `app/routers/sync.py`
4. Update normalizers if needed

### Improving Matching

The matching algorithm is in `app/core/matching.py`. Key files:

- `confidence.py` - Scoring weights and thresholds
- `classification.py` - Discrepancy type detection
- `ai_assist.py` - Claude integration

## Testing

```bash
pytest tests/
```

## License

Proprietary - Mesh, Inc.
