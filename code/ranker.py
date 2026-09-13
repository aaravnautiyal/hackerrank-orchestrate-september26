"""
Candidate Plan Generator & 6-Tier Tie-Breaker Decision Engine.
Evaluates payment options and selects optimal grounded decisions.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional
from code.schema import (
    AffordabilityStatus,
    FlexibleOption,
    PaymentMethod,
    PaymentPlanItem,
    PlanCandidate,
    PurchaseRequest,
    SpendingChangeItem,
    UserProfile,
)
from code.simulator import CashflowSimulator


class DecisionRanker:
    def __init__(self, simulator: CashflowSimulator):
        self.sim = simulator

    def _build_installment_schedule(
        self,
        request_date: date,
        down_payment: float,
        installment_amount: float,
        num_installments: int,
        installment_frequency_days: int,
    ) -> List[PaymentPlanItem]:
        """Constructs itemized payment plan items."""
        schedule = []
        if down_payment > 0:
            schedule.append(
                PaymentPlanItem(payment_date=request_date, amount=round(down_payment, 2))
            )

        curr_date = request_date
        for _ in range(num_installments):
            curr_date += timedelta(days=installment_frequency_days)
            schedule.append(
                PaymentPlanItem(payment_date=curr_date, amount=round(installment_amount, 2))
            )

        return schedule

    def evaluate_candidate_plan(
        self,
        option: FlexibleOption,
        request: PurchaseRequest,
        profile: UserProfile,
        initial_balance: float,
        daily_net: Dict[date, float],
        spending_changes: Optional[List[SpendingChangeItem]] = None,
    ) -> PlanCandidate:
        """Evaluates safety and metrics of a single flexible payment candidate option."""
        spending_changes = spending_changes or []

        if option.payment_method == PaymentMethod.FULL_PAYMENT:
            schedule_items = [
                PaymentPlanItem(
                    payment_date=request.request_date, amount=round(request.total_amount, 2)
                )
            ]
        elif option.payment_method == PaymentMethod.WAIT:
            earliest_date = self.sim.find_earliest_date_for_full_payment(
                initial_balance, profile, request.request_date, daily_net, request.total_amount
            )
            pay_date = (
                earliest_date if earliest_date else request.request_date + timedelta(days=90)
            )
            schedule_items = [
                PaymentPlanItem(payment_date=pay_date, amount=round(request.total_amount, 2))
            ]
        else:
            schedule_items = self._build_installment_schedule(
                request.request_date,
                option.down_payment,
                option.installment_amount,
                option.num_installments,
                option.installment_frequency_days,
            )

        # Convert schedule items to daily dict for simulator evaluation
        payment_dict: Dict[date, float] = {}
        total_cost = option.fee_amount
        for item in schedule_items:
            payment_dict[item.payment_date] = payment_dict.get(item.payment_date, 0.0) + item.amount
            total_cost += item.amount

        # Check balance safety constraint over 90 days
        is_safe = self.sim.is_plan_safe(
            initial_balance, profile, request.request_date, daily_net, payment_dict
        )

        first_payment_date = schedule_items[0].payment_date
        earliest_completion_date = schedule_items[-1].payment_date

        meets_desired_date = True
        if request.desired_completion_date:
            meets_desired_date = earliest_completion_date <= request.desired_completion_date

        return PlanCandidate(
            payment_option_id=option.option_id,
            recommended_payment_method=option.payment_method,
            payment_plan=schedule_items,
            spending_changes=spending_changes,
            total_cost=round(total_cost, 2),
            earliest_completion_date=earliest_completion_date,
            first_payment_date=first_payment_date,
            meets_desired_date=meets_desired_date,
            requires_spending_changes=len(spending_changes) > 0,
            is_valid_and_safe=is_safe,
        )

    def rank_candidates(self, candidates: List[PlanCandidate]) -> Optional[PlanCandidate]:
        """
        Applies strict 6-Tier Tie-Breaker logic to pick winning payment plan:
        1. Complete full request by desired_completion_date.
        2. Require zero spending changes (spending_changes_needed == "none").
        3. Minimize total amount paid (fees + principal).
        4. Start payment earlier (earliest first_payment_date).
        5. Use fewer payments.
        6. Lowest payment_option_id tie-breaker.
        """
        valid_candidates = [c for c in candidates if c.is_valid_and_safe]
        if not valid_candidates:
            return None

        def sorting_key(cand: PlanCandidate):
            return (
                0 if cand.meets_desired_date else 1,            # Tier 1
                0 if not cand.requires_spending_changes else 1, # Tier 2
                cand.total_cost,                                 # Tier 3
                cand.first_payment_date,                         # Tier 4
                len(cand.payment_plan),                          # Tier 5
                cand.payment_option_id                           # Tier 6
            )

        valid_candidates.sort(key=sorting_key)
        return valid_candidates[0]

    def determine_affordability_status(
        self,
        best_plan: Optional[PlanCandidate],
        amount_safe_to_pay: float,
        request: PurchaseRequest,
    ) -> AffordabilityStatus:
        """Determines final affordability classification tag."""
        if amount_safe_to_pay >= request.total_amount:
            return AffordabilityStatus.AFFORDABLE_NOW

        if best_plan:
            if best_plan.recommended_payment_method == PaymentMethod.WAIT:
                return AffordabilityStatus.AFFORDABLE_LATER
            elif best_plan.requires_spending_changes:
                return AffordabilityStatus.AFFORDABLE_WITH_PLAN
            elif best_plan.recommended_payment_method in [
                PaymentMethod.INSTALLMENTS,
                PaymentMethod.PARTIAL_PAYMENT,
            ]:
                return AffordabilityStatus.AFFORDABLE_WITH_PLAN

        return AffordabilityStatus.NOT_AFFORDABLE