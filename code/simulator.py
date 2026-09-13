"""
Deterministic 90-Day Cashflow Calculation and Constraint Engine.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Set
from code.schema import CashflowEvent, UserProfile, Frequency, SpendingChangeItem


class CashflowSimulator:
    def __init__(self, forecast_days: int = 90):
        self.forecast_days = forecast_days

    def convert_to_home_currency(
        self, amount: float, currency: str, home_currency: str, exchange_rates: Dict[Tuple[str, str], float]
    ) -> float:
        """Converts an amount to the user's home currency deterministically."""
        if currency == home_currency:
            return amount
        pair = (currency, home_currency)
        if pair in exchange_rates:
            return amount * exchange_rates[pair]
        raise ValueError(f"Exchange rate missing for pair: {pair}")

    def generate_daily_schedule(
        self,
        events: List[CashflowEvent],
        start_date: date,
        end_date: date,
        home_currency: str,
        exchange_rates: Dict[Tuple[str, str], float],
        spending_overrides: Optional[Dict[str, Optional[float]]] = None,
        cancelled_events: Optional[Set[str]] = None,
    ) -> Dict[date, float]:
        """
        Generates net daily cashflow delta (Inflows - Outflows) from start_date to end_date.
        """
        spending_overrides = spending_overrides or {}
        cancelled_events = cancelled_events or set()

        daily_net: Dict[date, float] = {}
        curr = start_date
        while curr <= end_date:
            daily_net[curr] = 0.0
            curr += timedelta(days=1)

        for event in events:
            if event.event_id in cancelled_events:
                continue

            # Determine base amount after overrides
            amount = event.amount
            if event.event_id in spending_overrides:
                override = spending_overrides[event.event_id]
                if override is None:
                    continue  # Stopped completely
                amount = override

            amount_home = self.convert_to_home_currency(amount, event.currency, home_currency, exchange_rates)
            signed_amount = amount_home if event.type.lower() == "inflow" else -amount_home

            # Recurrence application
            curr_evt_date = event.start_date
            evt_end = event.end_date if event.end_date else end_date

            while curr_evt_date <= min(evt_end, end_date):
                if curr_evt_date >= start_date:
                    daily_net[curr_evt_date] += signed_amount

                if event.frequency == Frequency.ONCE:
                    break
                elif event.frequency == Frequency.DAILY:
                    curr_evt_date += timedelta(days=1)
                elif event.frequency == Frequency.WEEKLY:
                    curr_evt_date += timedelta(weeks=1)
                elif event.frequency == Frequency.BIWEEKLY:
                    curr_evt_date += timedelta(weeks=2)
                elif event.frequency == Frequency.MONTHLY:
                    # Approximate 30-day billing cycle deterministically
                    curr_evt_date += timedelta(days=30)

        return daily_net

    def compute_90day_balance_vector(
        self,
        initial_balance: float,
        start_date: date,
        daily_net: Dict[date, float],
        outflow_schedule: Optional[Dict[date, float]] = None,
    ) -> List[Tuple[date, float]]:
        """
        Calculates balance vector B[t] = B[t-1] + Net[t] - RequestedOutflows[t] for 91 days.
        """
        outflow_schedule = outflow_schedule or {}
        balances = []
        current_bal = initial_balance

        for d in range(self.forecast_days + 1):
            curr_date = start_date + timedelta(days=d)
            net_flow = daily_net.get(curr_date, 0.0)
            requested_outflow = outflow_schedule.get(curr_date, 0.0)

            current_bal = current_bal + net_flow - requested_outflow
            balances.append((curr_date, current_bal))

        return balances

    def is_plan_safe(
        self,
        initial_balance: float,
        profile: UserProfile,
        start_date: date,
        daily_net: Dict[date, float],
        payment_schedule: Dict[date, float],
    ) -> bool:
        """Evaluates constraint: B[t] >= minimum_balance_to_keep for all t in [0, 90]."""
        balances = self.compute_90day_balance_vector(initial_balance, start_date, daily_net, payment_schedule)
        return all(bal >= profile.minimum_balance_to_keep for _, bal in balances)

    def calculate_amount_safe_to_pay(
        self,
        initial_balance: float,
        profile: UserProfile,
        request_date: date,
        daily_net: Dict[date, float],
        max_amount: float,
    ) -> float:
        """
        Binary search engine to compute maximum safe immediate payment on request_date
        without violating minimum balance constraints over 90 days.
        """
        low = 0.0
        high = max_amount
        safe_amount = 0.0
        tolerance = 0.01

        while high - low > tolerance:
            mid = (low + high) / 2.0
            schedule = {request_date: mid}
            if self.is_plan_safe(initial_balance, profile, request_date, daily_net, schedule):
                safe_amount = mid
                low = mid
            else:
                high = mid

        return round(safe_amount, 2)

    def find_earliest_date_for_full_payment(
        self,
        initial_balance: float,
        profile: UserProfile,
        request_date: date,
        daily_net: Dict[date, float],
        full_amount: float,
    ) -> Optional[date]:
        """Scans forward day-by-day up to day 90 to find the earliest safe lump-sum payment date."""
        for d in range(self.forecast_days + 1):
            target_date = request_date + timedelta(days=d)
            schedule = {target_date: full_amount}
            if self.is_plan_safe(initial_balance, profile, request_date, daily_net, schedule):
                return target_date
        return None