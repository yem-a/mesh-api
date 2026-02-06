# app/core/matching.py

"""
Core transaction matching engine.

This is the MOAT - the deterministic matching algorithm that pairs
Stripe transactions with QuickBooks entries.
"""

from datetime import date, datetime
from typing import Optional
import uuid

from app.models import (
    TransactionCreate,
    ConfidenceBreakdown,
    DiscrepancyClassification,
    MatchDB,
    UnmatchedTransaction,
    PossibleMatch,
    ReconciliationSummary,
)
from app.core.confidence import calculate_confidence
from app.core.classification import (
    classify_discrepancy,
    classify_unmatched,
    determine_priority,
)
from app.config import get_settings

settings = get_settings()


class ReconciliationResult:
    """Result of a reconciliation run."""

    def __init__(self):
        self.matched: list[MatchDB] = []
        self.unmatched_stripe: list[UnmatchedTransaction] = []
        self.unmatched_qbo: list[UnmatchedTransaction] = []
        self.summary: Optional[ReconciliationSummary] = None
        self.period_start: Optional[date] = None
        self.period_end: Optional[date] = None
        self.duration_ms: int = 0

    @property
    def discrepancies(self) -> dict:
        """Categorize matches by discrepancy severity."""
        critical = []
        warnings = []
        info = []

        for match in self.matched:
            if match.has_discrepancy:
                if match.discrepancy_severity == "critical":
                    critical.append(match)
                elif match.discrepancy_severity == "warning":
                    warnings.append(match)
                else:
                    info.append(match)

        return {
            "critical": critical,
            "warnings": warnings,
            "info": info,
        }

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "summary": self.summary.model_dump() if self.summary else None,
            "matched": [m.model_dump() for m in self.matched],
            "unmatched_stripe": [u.model_dump() for u in self.unmatched_stripe],
            "unmatched_qbo": [u.model_dump() for u in self.unmatched_qbo],
            "discrepancies": {
                "critical": len(self.discrepancies["critical"]),
                "warnings": len(self.discrepancies["warnings"]),
                "info": len(self.discrepancies["info"]),
            },
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "duration_ms": self.duration_ms,
        }


def reconcile(
    stripe_transactions: list[TransactionCreate],
    qbo_transactions: list[TransactionCreate],
    user_id: str,
) -> ReconciliationResult:
    """
    Main reconciliation function.

    Matches Stripe transactions with QuickBooks entries using a multi-pass approach:
    1. Separate transactions by type (charges vs refunds)
    2. Match charges against QB payments (4-phase)
    3. Match refunds against QB credits (2-phase)
    4. Collect unmatched with possible candidates
    """
    start_time = datetime.now()
    result = ReconciliationResult()

    # Track what's been matched
    matched_stripe_ids: set[str] = set()
    matched_qbo_ids: set[str] = set()

    # ============================================
    # Separate transactions by type
    # ============================================
    stripe_charges = [t for t in stripe_transactions if getattr(t, "transaction_type", "charge") == "charge"]
    stripe_refunds = [t for t in stripe_transactions if getattr(t, "transaction_type", "charge") == "refund"]

    # Separate QB transactions: positive amounts = payments, negative = credits
    qbo_payments = []
    qbo_credits = []
    for t in qbo_transactions:
        txn_type = getattr(t, "transaction_type", "payment")
        if txn_type in ("credit_memo", "refund") or t.amount < 0:
            qbo_credits.append(t)
        else:
            qbo_payments.append(t)

    # ============================================
    # Match charges against QB payments (full 4-phase)
    # ============================================
    sorted_charges = sorted(stripe_charges, key=lambda t: t.amount, reverse=True)
    sorted_payments = sorted(qbo_payments, key=lambda t: t.amount, reverse=True)

    # Phase 1: High-confidence matches (auto-match)
    for stripe in sorted_charges:
        if stripe.external_id in matched_stripe_ids:
            continue

        for qbo in sorted_payments:
            if qbo.external_id in matched_qbo_ids:
                continue

            confidence = calculate_confidence(stripe, qbo)

            if confidence.level == "high":
                match = _create_match(
                    stripe, qbo, confidence,
                    status="auto_matched",
                    user_id=user_id,
                )
                result.matched.append(match)
                matched_stripe_ids.add(stripe.external_id)
                matched_qbo_ids.add(qbo.external_id)
                break

    # Phase 2: Medium-confidence matches (suggested)
    for stripe in sorted_charges:
        if stripe.external_id in matched_stripe_ids:
            continue

        best_match: Optional[tuple[TransactionCreate, ConfidenceBreakdown]] = None

        for qbo in sorted_payments:
            if qbo.external_id in matched_qbo_ids:
                continue

            confidence = calculate_confidence(stripe, qbo)

            if confidence.level == "medium":
                if best_match is None or confidence.total > best_match[1].total:
                    best_match = (qbo, confidence)

        if best_match:
            qbo, confidence = best_match
            match = _create_match(
                stripe, qbo, confidence,
                status="suggested",
                user_id=user_id,
            )
            result.matched.append(match)
            matched_stripe_ids.add(stripe.external_id)
            matched_qbo_ids.add(qbo.external_id)

    # Phase 3: Fee-adjusted matches
    for stripe in sorted_charges:
        if stripe.external_id in matched_stripe_ids:
            continue

        fee_match = _find_fee_adjusted_match(stripe, sorted_payments, matched_qbo_ids)

        if fee_match:
            qbo, confidence = fee_match
            match = _create_match(
                stripe, qbo, confidence,
                status="suggested",
                user_id=user_id,
            )
            result.matched.append(match)
            matched_stripe_ids.add(stripe.external_id)
            matched_qbo_ids.add(qbo.external_id)

    # ============================================
    # Match refunds against QB credits (phases 1-2 only)
    # ============================================
    sorted_refunds = sorted(stripe_refunds, key=lambda t: abs(t.amount), reverse=True)
    sorted_credits = sorted(qbo_credits, key=lambda t: abs(t.amount), reverse=True)

    # Phase 1: High-confidence refund matches
    for stripe in sorted_refunds:
        if stripe.external_id in matched_stripe_ids:
            continue

        for qbo in sorted_credits:
            if qbo.external_id in matched_qbo_ids:
                continue

            confidence = calculate_confidence(stripe, qbo)

            if confidence.level == "high":
                match = _create_match(
                    stripe, qbo, confidence,
                    status="auto_matched",
                    user_id=user_id,
                )
                result.matched.append(match)
                matched_stripe_ids.add(stripe.external_id)
                matched_qbo_ids.add(qbo.external_id)
                break

    # Phase 2: Medium-confidence refund matches
    for stripe in sorted_refunds:
        if stripe.external_id in matched_stripe_ids:
            continue

        best_match = None

        for qbo in sorted_credits:
            if qbo.external_id in matched_qbo_ids:
                continue

            confidence = calculate_confidence(stripe, qbo)

            if confidence.level == "medium":
                if best_match is None or confidence.total > best_match[1].total:
                    best_match = (qbo, confidence)

        if best_match:
            qbo, confidence = best_match
            match = _create_match(
                stripe, qbo, confidence,
                status="suggested",
                user_id=user_id,
            )
            result.matched.append(match)
            matched_stripe_ids.add(stripe.external_id)
            matched_qbo_ids.add(qbo.external_id)

    # ============================================
    # Phase 4: Collect unmatched transactions
    # ============================================
    today = date.today()

    # All unmatched Stripe (charges + refunds)
    all_stripe = sorted_charges + sorted_refunds
    all_qbo = sorted_payments + sorted_credits

    for stripe in all_stripe:
        if stripe.external_id in matched_stripe_ids:
            continue

        # Find possible matches from the appropriate QB pool
        candidates = sorted_credits if getattr(stripe, "transaction_type", "charge") == "refund" else sorted_payments
        possible = _find_possible_matches(stripe, candidates, matched_qbo_ids)
        days_old = (today - stripe.transaction_date).days

        unmatched = UnmatchedTransaction(
            transaction=stripe,
            possible_matches=possible,
            classification=classify_unmatched(stripe, "stripe"),
            days_old=days_old,
            priority=determine_priority(stripe, days_old),
        )
        result.unmatched_stripe.append(unmatched)

    for qbo in all_qbo:
        if qbo.external_id in matched_qbo_ids:
            continue

        # Find possible matches from the appropriate Stripe pool
        candidates = sorted_refunds if qbo.amount < 0 else sorted_charges
        possible = _find_possible_matches(qbo, candidates, matched_stripe_ids, reverse=True)
        days_old = (today - qbo.transaction_date).days

        unmatched = UnmatchedTransaction(
            transaction=qbo,
            possible_matches=possible,
            classification=classify_unmatched(qbo, "quickbooks"),
            days_old=days_old,
            priority=determine_priority(qbo, days_old),
        )
        result.unmatched_qbo.append(unmatched)

    # ============================================
    # Calculate summary
    # ============================================
    total_stripe = sum(t.amount for t in stripe_transactions)
    total_qbo = sum(t.amount for t in qbo_transactions)
    auto_matched = len([m for m in result.matched if m.status == "auto_matched"])

    result.summary = ReconciliationSummary(
        total_stripe_transactions=len(stripe_transactions),
        total_qbo_transactions=len(qbo_transactions),
        total_stripe_amount=total_stripe,
        total_qbo_amount=total_qbo,
        net_difference=total_stripe - total_qbo,
        match_rate=(len(result.matched) / len(stripe_transactions) * 100) if stripe_transactions else 0,
        auto_match_rate=(auto_matched / len(stripe_transactions) * 100) if stripe_transactions else 0,
    )

    # Set period
    all_dates = [t.transaction_date for t in stripe_transactions + qbo_transactions]
    if all_dates:
        result.period_start = min(all_dates)
        result.period_end = max(all_dates)

    result.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    return result


def _create_match(
    stripe: TransactionCreate,
    qbo: TransactionCreate,
    confidence: ConfidenceBreakdown,
    status: str,
    user_id: str,
) -> MatchDB:
    """Create a match record."""

    # Classify any discrepancy
    discrepancy = None
    if confidence.total < 100:
        discrepancy = classify_discrepancy(stripe, qbo)

    match = MatchDB(
        id=str(uuid.uuid4()),
        user_id=user_id,
        stripe_external_id=stripe.external_id,
        qbo_external_id=qbo.external_id,
        confidence_total=confidence.total,
        confidence_level=confidence.level,
        confidence_breakdown={
            "amount_score": confidence.amount_score,
            "date_score": confidence.date_score,
            "customer_score": confidence.customer_score,
            "description_score": confidence.description_score,
            "factors": confidence.factors,
        },
        match_reason=confidence.factors[0] if confidence.factors else "Manual review",
        status=status,
        has_discrepancy=discrepancy is not None and discrepancy.type != "unknown",
        discrepancy_type=discrepancy.type if discrepancy else None,
        discrepancy_severity=discrepancy.severity if discrepancy else None,
        discrepancy_explanation=discrepancy.explanation if discrepancy else None,
        discrepancy_suggested_action=discrepancy.suggested_action if discrepancy else None,
        discrepancy_auto_resolvable=discrepancy.auto_resolvable if discrepancy else False,
        amount_difference=discrepancy.amount_difference if discrepancy else None,
        date_difference_days=discrepancy.date_difference_days if discrepancy else None,
    )

    return match


def _find_fee_adjusted_match(
    stripe: TransactionCreate,
    qbo_transactions: list[TransactionCreate],
    matched_qbo_ids: set[str],
) -> Optional[tuple[TransactionCreate, ConfidenceBreakdown]]:
    """
    Find a match where QBO recorded the net amount after Stripe fees.

    Uses actual fee data from metadata when available, otherwise estimates.
    """
    # Use actual fee from metadata if available
    actual_fee = None
    if stripe.metadata:
        actual_fee = stripe.metadata.get("fee_amount")

    if actual_fee is not None:
        expected_net = stripe.amount - actual_fee
    else:
        expected_fee = (stripe.amount * settings.stripe_fee_percent / 100) + settings.stripe_fee_fixed
        expected_net = stripe.amount - expected_fee

    for qbo in qbo_transactions:
        if qbo.external_id in matched_qbo_ids:
            continue

        # Check if QBO amount matches expected net
        if abs(expected_net - qbo.amount) < (stripe.amount * 0.005):  # Within 0.5%
            # Check date is reasonable
            days_diff = abs((stripe.transaction_date - qbo.transaction_date).days)
            if days_diff <= settings.date_tolerance_days:
                fee_source = "actual" if actual_fee is not None else "estimated"
                confidence = ConfidenceBreakdown(
                    amount_score=30,
                    date_score=25 if days_diff <= 1 else 20,
                    customer_score=0,
                    description_score=0,
                    total=55 + (5 if days_diff == 0 else 0),
                    level="medium",
                    factors=[
                        f"Amount matches after Stripe fee adjustment ({fee_source} fee)",
                        f"Stripe gross: ${stripe.amount:,.2f}",
                        f"Expected net: ${expected_net:,.2f}",
                        f"QuickBooks: ${qbo.amount:,.2f}",
                    ],
                )
                return (qbo, confidence)

    return None


def _find_possible_matches(
    transaction: TransactionCreate,
    candidates: list[TransactionCreate],
    exclude_ids: set[str],
    reverse: bool = False,
) -> list[PossibleMatch]:
    """Find possible match candidates for an unmatched transaction."""
    possible: list[PossibleMatch] = []

    for candidate in candidates:
        if candidate.external_id in exclude_ids:
            continue

        # Calculate confidence
        if reverse:
            confidence = calculate_confidence(candidate, transaction)
        else:
            confidence = calculate_confidence(transaction, candidate)

        # Include if there's some match potential
        if confidence.total >= 30:
            why_not = _generate_why_not_matched(confidence)
            possible.append(PossibleMatch(
                transaction=candidate,
                confidence=confidence,
                why_not_auto_matched=why_not,
            ))

    # Sort by confidence and take top 3
    possible.sort(key=lambda p: p.confidence.total, reverse=True)
    return possible[:3]


def _generate_why_not_matched(confidence: ConfidenceBreakdown) -> str:
    """Generate explanation for why this wasn't auto-matched."""
    issues = []

    if confidence.amount_score < 25:
        issues.append("amount differs significantly")
    if confidence.date_score < 15:
        issues.append("dates too far apart")
    if confidence.customer_score == 0:
        issues.append("no customer match")
    if confidence.total < settings.auto_match_threshold:
        issues.append(f"confidence {confidence.total} below threshold {settings.auto_match_threshold}")

    if issues:
        return f"Not auto-matched: {', '.join(issues)}"
    return "Below confidence threshold"
