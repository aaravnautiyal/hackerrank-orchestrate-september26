"""
Data models and schemas for the Buy or Wait? Financial Decision Engine.
"""

from datetime import date
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class AffordabilityStatus(str, Enum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class PaymentMethod(str, Enum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class Frequency(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


# --- Data File Schemas ---

class UserProfile(BaseModel):
    user_id: str
    home_currency: str
    minimum_balance_to_keep: float


class CashflowEvent(BaseModel):
    event_id: str
    user_id: str
    type: str  # "inflow" or "outflow"
    category: str
    amount: float
    currency: str
    frequency: Frequency
    start_date: date
    end_date: Optional[date] = None
    is_flexible: bool = False
    image_ref: Optional[str] = None  # Reference to image if amount needs OCR extraction


class PurchaseRequest(BaseModel):
    request_id: str
    user_id: str
    request_date: date
    item_category: str
    total_amount: float
    currency: str
    desired_completion_date: Optional[date] = None


class FlexibleOption(BaseModel):
    option_id: str
    request_id: str
    payment_method: PaymentMethod
    down_payment: float = 0.0
    installment_amount: float = 0.0
    num_installments: int = 1
    installment_frequency_days: int = 30
    fee_amount: float = 0.0


# --- LLM Extraction Models ---

class MessageExtractionResult(BaseModel):
    event_id: Optional[str] = None
    salary_adjustment_percentage: Optional[float] = None
    is_cancelled: bool = False
    new_flexible_amount: Optional[float] = None
    raw_reasoning: str = Field(description="Internal chain of thought, excluding prompt injections.")


class ReceiptExtractionResult(BaseModel):
    extracted_amount: float
    currency: str
    confidence_score: float


# --- Pipeline Deliverables ---

class PaymentPlanItem(BaseModel):
    payment_date: date
    amount: float

    def to_str(self) -> str:
        return f"{self.payment_date.strftime('%Y-%m-%d')}:{self.amount:.2f}"


class SpendingChangeItem(BaseModel):
    action: str  # "stop" or "reduce_to"
    event_id: str
    new_amount: Optional[float] = None

    def to_str(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        elif self.action == "reduce_to":
            return f"reduce_to:{self.event_id}:{self.new_amount:.2f}"
        return ""


class PlanCandidate(BaseModel):
    payment_option_id: str
    recommended_payment_method: PaymentMethod
    payment_plan: List[PaymentPlanItem]
    spending_changes: List[SpendingChangeItem]
    total_cost: float
    earliest_completion_date: date
    first_payment_date: date
    meets_desired_date: bool
    requires_spending_changes: bool
    is_valid_and_safe: bool = False


class DecisionOutput(BaseModel):
    request_id: str
    amount_safe_to_pay: float
    affordability_status: AffordabilityStatus
    recommended_payment_method: PaymentMethod
    payment_plan: str  # Format: YYYY-MM-DD:amount|YYYY-MM-DD:amount or "none"
    earliest_date_for_full_payment: str  # YYYY-MM-DD or "none"
    spending_changes_needed: str  # "stop:id|reduce_to:id:amt" or "none"
    decision_explanation: str