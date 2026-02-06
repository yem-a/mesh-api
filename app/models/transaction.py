# app/models/transaction.py

from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field

TransactionType = Literal["charge", "refund", "payment", "invoice", "credit_memo", "other"]


class Transaction(BaseModel):
    """A transaction from Stripe or QuickBooks."""

    id: str
    external_id: str
    source: Literal["stripe", "quickbooks"]
    transaction_type: TransactionType = "charge"
    amount: float
    transaction_date: date
    description: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    metadata: Optional[dict] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class TransactionCreate(BaseModel):
    """Transaction data from external source."""

    external_id: str
    source: Literal["stripe", "quickbooks"]
    transaction_type: TransactionType = "charge"
    amount: float
    transaction_date: date
    description: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    metadata: Optional[dict] = Field(default_factory=dict)


class StripeCharge(BaseModel):
    """Stripe charge mapped to our format."""
    
    id: str
    amount: float  # Already converted from cents
    created: datetime
    description: Optional[str] = None
    customer: Optional[str] = None
    customer_name: Optional[str] = None
    status: str
    
    def to_transaction(self) -> TransactionCreate:
        return TransactionCreate(
            external_id=self.id,
            source="stripe",
            transaction_type="charge",
            amount=self.amount,
            transaction_date=self.created.date(),
            description=self.description,
            customer_id=self.customer,
            customer_name=self.customer_name,
        )


class QuickBooksPayment(BaseModel):
    """QuickBooks payment mapped to our format."""
    
    id: str
    total_amount: float
    txn_date: date
    private_note: Optional[str] = None
    customer_ref: Optional[str] = None
    customer_name: Optional[str] = None
    
    def to_transaction(self) -> TransactionCreate:
        return TransactionCreate(
            external_id=self.id,
            source="quickbooks",
            amount=self.total_amount,
            transaction_date=self.txn_date,
            description=self.private_note,
            customer_id=self.customer_ref,
            customer_name=self.customer_name,
        )
