# app/core/classification.py

"""
Discrepancy classification for transaction matching.

Classifies the type and severity of discrepancies between matched transactions.
"""

from datetime import date
from app.models import (
    TransactionCreate,
    DiscrepancyClassification,
    DiscrepancyType,
    DiscrepancySeverity,
)
from app.config import get_settings

settings = get_settings()


def classify_discrepancy(
    stripe: TransactionCreate,
    qbo: TransactionCreate | None,
) -> DiscrepancyClassification:
    """
    Classify the discrepancy between a Stripe transaction and its QuickBooks match.
    
    Returns a DiscrepancyClassification with type, severity, and suggested action.
    """
    
    # ============================================
    # Missing in QuickBooks
    # ============================================
    if qbo is None:
        return DiscrepancyClassification(
            type="missing_in_qbo",
            severity="critical",
            explanation=f"Transaction {stripe.external_id} (${stripe.amount:,.2f}) exists in Stripe but has no matching entry in QuickBooks.",
            suggested_action="Create a corresponding invoice or payment in QuickBooks",
            auto_resolvable=False,
        )
    
    # Calculate differences
    amount_diff = stripe.amount - qbo.amount
    amount_diff_abs = abs(amount_diff)
    amount_diff_percent = (amount_diff_abs / stripe.amount * 100) if stripe.amount > 0 else 0
    days_diff = (stripe.transaction_date - qbo.transaction_date).days
    
    # ============================================
    # Check for Stripe fee pattern
    # ============================================
    expected_fee = _calculate_stripe_fee(stripe.amount)
    fee_variance = abs(amount_diff - expected_fee)
    is_fee_pattern = fee_variance < (stripe.amount * 0.005)  # Within 0.5%
    
    if is_fee_pattern and amount_diff > 0:
        return DiscrepancyClassification(
            type="fee_not_recorded",
            severity="warning",
            explanation=(
                f"QuickBooks shows ${qbo.amount:,.2f} but Stripe charged ${stripe.amount:,.2f}. "
                f"The ${amount_diff:,.2f} difference likely represents Stripe processing fees "
                f"({settings.stripe_fee_percent}% + ${settings.stripe_fee_fixed})."
            ),
            suggested_action=f"Record a fee expense of ${amount_diff:,.2f} in QuickBooks",
            auto_resolvable=True,
            amount_difference=amount_diff,
        )
    
    # ============================================
    # Timing difference (amounts match, dates don't)
    # ============================================
    if amount_diff_abs < 0.01 and abs(days_diff) > settings.date_tolerance_days:
        return DiscrepancyClassification(
            type="timing_difference",
            severity="info",
            explanation=(
                f"Amounts match exactly, but dates differ by {abs(days_diff)} days. "
                f"Stripe: {stripe.transaction_date.strftime('%b %d')}, "
                f"QuickBooks: {qbo.transaction_date.strftime('%b %d')}."
            ),
            suggested_action="Verify the transaction dates are acceptable for your records",
            auto_resolvable=False,
            date_difference_days=abs(days_diff),
        )
    
    # ============================================
    # Partial payment pattern
    # ============================================
    if qbo.amount < stripe.amount and amount_diff_percent > 10:
        return DiscrepancyClassification(
            type="partial_payment",
            severity="warning",
            explanation=(
                f"QuickBooks shows ${qbo.amount:,.2f} but Stripe shows ${stripe.amount:,.2f}. "
                f"This could be a partial payment or split transaction."
            ),
            suggested_action="Check if there are additional related payments or if this needs adjustment",
            auto_resolvable=False,
            amount_difference=amount_diff,
        )
    
    # ============================================
    # General amount mismatch
    # ============================================
    if amount_diff_abs > 0.01:
        severity: DiscrepancySeverity = "critical" if amount_diff_percent > 10 else "warning"
        
        return DiscrepancyClassification(
            type="amount_mismatch",
            severity=severity,
            explanation=(
                f"Amount discrepancy of ${amount_diff_abs:,.2f} ({amount_diff_percent:.1f}%). "
                f"Stripe: ${stripe.amount:,.2f}, QuickBooks: ${qbo.amount:,.2f}."
            ),
            suggested_action="Review both transactions to identify the source of the discrepancy",
            auto_resolvable=False,
            amount_difference=amount_diff,
        )
    
    # ============================================
    # No discrepancy detected
    # ============================================
    return DiscrepancyClassification(
        type="unknown",
        severity="info",
        explanation="This match requires manual review",
        suggested_action="Review the transaction details",
        auto_resolvable=False,
    )


def classify_unmatched(
    transaction: TransactionCreate,
    source: str,
) -> DiscrepancyClassification:
    """Classify an unmatched transaction."""

    if source == "stripe":
        if getattr(transaction, "transaction_type", "charge") == "refund":
            return DiscrepancyClassification(
                type="refund_not_recorded",
                severity="warning",
                explanation=(
                    f"Refund {transaction.external_id} (${abs(transaction.amount):,.2f}) "
                    f"exists in Stripe but has no matching credit in QuickBooks."
                ),
                suggested_action="Create a credit memo or refund receipt in QuickBooks",
                auto_resolvable=False,
                amount_difference=abs(transaction.amount),
            )
        return DiscrepancyClassification(
            type="missing_in_qbo",
            severity="critical",
            explanation=(
                f"Transaction {transaction.external_id} (${transaction.amount:,.2f}) "
                f"exists in Stripe but has no matching entry in QuickBooks."
            ),
            suggested_action="Create a corresponding invoice or payment in QuickBooks",
            auto_resolvable=False,
        )
    else:
        return DiscrepancyClassification(
            type="missing_in_stripe",
            severity="warning",
            explanation=(
                f"QuickBooks entry {transaction.external_id} (${abs(transaction.amount):,.2f}) "
                f"has no matching Stripe transaction. This may be a manual payment."
            ),
            suggested_action="Verify this payment was received outside of Stripe",
            auto_resolvable=False,
        )


def _calculate_stripe_fee(amount: float) -> float:
    """Calculate expected Stripe fee for an amount."""
    return (amount * settings.stripe_fee_percent / 100) + settings.stripe_fee_fixed


def determine_priority(
    transaction: TransactionCreate,
    days_old: int,
) -> str:
    """Determine priority for an unmatched transaction."""
    
    # High priority: large amounts or old transactions
    if transaction.amount > 1000 or days_old > 14:
        return "high"
    
    # Low priority: small amounts and recent
    if transaction.amount < 100 and days_old < 7:
        return "low"
    
    return "medium"
