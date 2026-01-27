# tests/test_matching.py

"""
Tests for the core matching engine.
"""

import pytest
from datetime import date

from app.models import TransactionCreate
from app.core.matching import reconcile
from app.core.confidence import calculate_confidence
from app.core.classification import classify_discrepancy


# ============================================
# Test Data
# ============================================

def make_stripe_txn(
    id: str,
    amount: float,
    txn_date: date,
    customer_name: str = None,
) -> TransactionCreate:
    return TransactionCreate(
        external_id=id,
        source="stripe",
        amount=amount,
        transaction_date=txn_date,
        description=f"Stripe charge {id}",
        customer_name=customer_name,
    )


def make_qbo_txn(
    id: str,
    amount: float,
    txn_date: date,
    customer_name: str = None,
) -> TransactionCreate:
    return TransactionCreate(
        external_id=id,
        source="quickbooks",
        amount=amount,
        transaction_date=txn_date,
        description=f"QB payment {id}",
        customer_name=customer_name,
    )


# ============================================
# Confidence Scoring Tests
# ============================================

class TestConfidenceScoring:
    """Test the confidence scoring algorithm."""
    
    def test_exact_match_high_confidence(self):
        """Exact amount and same day should be high confidence."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15), "Acme Corp")
        qbo = make_qbo_txn("qbo_1", 100.00, date(2025, 1, 15), "Acme Corp")
        
        confidence = calculate_confidence(stripe, qbo)
        
        assert confidence.level == "high"
        assert confidence.total >= 85
        assert confidence.amount_score == 40  # Exact match
        assert confidence.date_score == 30    # Same day
    
    def test_amount_mismatch_lowers_confidence(self):
        """Significant amount difference should lower confidence."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15))
        qbo = make_qbo_txn("qbo_1", 80.00, date(2025, 1, 15))
        
        confidence = calculate_confidence(stripe, qbo)
        
        assert confidence.level != "high"
        assert confidence.amount_score < 20
    
    def test_date_tolerance(self):
        """Dates within 3 days should still score well."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15))
        qbo = make_qbo_txn("qbo_1", 100.00, date(2025, 1, 17))  # 2 days later
        
        confidence = calculate_confidence(stripe, qbo)
        
        assert confidence.date_score >= 20
    
    def test_customer_name_match(self):
        """Customer name match should add confidence."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15), "Acme Corporation")
        qbo = make_qbo_txn("qbo_1", 100.00, date(2025, 1, 15), "Acme Corp")
        
        confidence = calculate_confidence(stripe, qbo)
        
        assert confidence.customer_score > 0
        assert "Customer name" in str(confidence.factors) or "customer" in str(confidence.factors).lower()


# ============================================
# Discrepancy Classification Tests
# ============================================

class TestDiscrepancyClassification:
    """Test the discrepancy classification."""
    
    def test_missing_in_qbo(self):
        """Missing QBO transaction should be critical."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15))
        
        classification = classify_discrepancy(stripe, None)
        
        assert classification.type == "missing_in_qbo"
        assert classification.severity == "critical"
    
    def test_fee_detection(self):
        """Should detect Stripe fee pattern."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15))
        # Net after 2.9% + $0.30 fee = 100 - 3.20 = 96.80
        qbo = make_qbo_txn("qbo_1", 96.80, date(2025, 1, 15))
        
        classification = classify_discrepancy(stripe, qbo)
        
        assert classification.type == "fee_not_recorded"
        assert classification.auto_resolvable == True
    
    def test_timing_difference(self):
        """Same amount with date gap should be timing difference."""
        stripe = make_stripe_txn("ch_1", 100.00, date(2025, 1, 15))
        qbo = make_qbo_txn("qbo_1", 100.00, date(2025, 1, 22))  # 7 days later
        
        classification = classify_discrepancy(stripe, qbo)
        
        assert classification.type == "timing_difference"
        assert classification.severity == "info"


# ============================================
# Full Reconciliation Tests
# ============================================

class TestReconciliation:
    """Test the full reconciliation flow."""
    
    def test_basic_reconciliation(self):
        """Basic reconciliation with some matches."""
        stripe_txns = [
            make_stripe_txn("ch_1", 100.00, date(2025, 1, 15), "Acme"),
            make_stripe_txn("ch_2", 250.00, date(2025, 1, 16), "TechCorp"),
            make_stripe_txn("ch_3", 500.00, date(2025, 1, 17)),  # No match
        ]
        
        qbo_txns = [
            make_qbo_txn("qbo_1", 100.00, date(2025, 1, 15), "Acme"),
            make_qbo_txn("qbo_2", 250.00, date(2025, 1, 16), "TechCorp"),
        ]
        
        result = reconcile(stripe_txns, qbo_txns, "test_user")
        
        assert len(result.matched) == 2
        assert len(result.unmatched_stripe) == 1
        assert len(result.unmatched_qbo) == 0
        assert result.summary.match_rate > 50
    
    def test_fee_adjusted_matching(self):
        """Should match transactions where QBO has net amount."""
        stripe_txns = [
            make_stripe_txn("ch_1", 1000.00, date(2025, 1, 15)),
        ]
        
        # Net after fees: 1000 - (1000 * 0.029 + 0.30) = 1000 - 29.30 = 970.70
        qbo_txns = [
            make_qbo_txn("qbo_1", 970.70, date(2025, 1, 15)),
        ]
        
        result = reconcile(stripe_txns, qbo_txns, "test_user")
        
        assert len(result.matched) == 1
        assert result.matched[0].discrepancy_type == "fee_not_recorded"
    
    def test_empty_transactions(self):
        """Should handle empty transaction lists."""
        result = reconcile([], [], "test_user")
        
        assert len(result.matched) == 0
        assert result.summary.total_stripe_transactions == 0
        assert result.summary.match_rate == 0


# ============================================
# Run Tests
# ============================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
