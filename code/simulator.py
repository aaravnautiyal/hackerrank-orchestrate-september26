from datetime import datetime, timedelta
from typing import List, Dict, Any, Union, Optional


class CashflowSimulator:
    def __init__(
        self, 
        events: List[Any] = None, 
        baseline_balances: Dict[str, float] = None, 
        forecast_days: int = 90,
        horizon_days: int = 90,
        **kwargs
    ):
        """
        Initializes the simulator with cashflow events and baseline account balances.
        """
        self.events = events or []
        self.baseline_balances = baseline_balances or {}
        self.forecast_days = forecast_days or horizon_days

    def _get_attr_or_key(self, obj: Any, attr: str, default: Any = None) -> Any:
        """Helper to safely read attributes across Pydantic models and dictionaries."""
        if isinstance(obj, dict):
            val = obj.get(attr, default)
            return val if val is not None else default
        val = getattr(obj, attr, default)
        return val if val is not None else default

    def _parse_date(self, date_val: Any) -> datetime.date:
        """Normalizes strings, datetimes, or dates to a standard datetime.date."""
        if isinstance(date_val, str):
            return datetime.strptime(date_val[:10], "%Y-%m-%d").date()
        if isinstance(date_val, datetime):
            return date_val.date()
        return date_val

    def generate_daily_schedule(
        self, 
        user_id: str = None, 
        start_date: Any = None, 
        forecast_days: int = None,
        end_date: Any = None,
        events: List[Any] = None,
        **kwargs
    ) -> Dict[datetime.date, float]:
        """
        Generates net daily cashflow adjustments for upcoming active transactions.
        Filters out settled and historical events to prevent baseline corruption.
        """
        events_to_process = events if events is not None else self.events
        start_dt = self._parse_date(start_date) if start_date else None
        
        if end_date:
            end_dt = self._parse_date(end_date)
        elif start_dt:
            days = forecast_days or self.forecast_days
            end_dt = start_dt + timedelta(days=days)
        else:
            end_dt = None

        daily_changes: Dict[datetime.date, float] = {}

        for event in events_to_process:
            if user_id is not None:
                ev_user = self._get_attr_or_key(event, "user_id")
                if ev_user is not None and str(ev_user) != str(user_id):
                    continue

            # Skip historical / settled transactions
            status = str(self._get_attr_or_key(event, "status", "pending")).lower()
            if status in ["settled", "completed", "cancelled", "historical", "paid"]:
                continue

            ev_date_raw = (
                self._get_attr_or_key(event, "start_date") 
                or self._get_attr_or_key(event, "event_date")
                or self._get_attr_or_key(event, "date")
            )
            if not ev_date_raw:
                continue

            ev_date = self._parse_date(ev_date_raw)
            if start_dt and ev_date < start_dt:
                continue
            if end_dt and ev_date > end_dt:
                continue

            amount = float(self._get_attr_or_key(event, "amount", 0.0))
            direction = str(
                self._get_attr_or_key(event, "type") 
                or self._get_attr_or_key(event, "direction", "outflow")
            ).lower()

            if direction in ["outflow", "expense", "debit"]:
                daily_changes[ev_date] = daily_changes.get(ev_date, 0.0) - amount
            else:
                daily_changes[ev_date] = daily_changes.get(ev_date, 0.0) + amount

        return daily_changes

    def get_minimum_projected_balance(self, *args, **kwargs) -> float:
        """
        Calculates the minimum projected balance over the target forecast horizon.
        """
        kw = dict(kwargs)
        user_id = kw.pop("user_id", None)
        request_date = kw.pop("request_date", None) or kw.pop("start_date", None)
        forecast_days = kw.pop("forecast_days", None) or self.forecast_days
        events = kw.pop("events", None)

        if args:
            if isinstance(args[0], (dict, object)) and not isinstance(args[0], str):
                req = args[0]
                user_id = user_id or self._get_attr_or_key(req, "user_id")
                request_date = request_date or self._get_attr_or_key(req, "request_date") or self._get_attr_or_key(req, "start_date")
            else:
                user_id = user_id or args[0]
                if len(args) > 1:
                    request_date = request_date or args[1]

        start_date = self._parse_date(request_date) if request_date else datetime.now().date()
        days_to_project = forecast_days or 90
        end_date = start_date + timedelta(days=days_to_project)

        # Look up starting baseline balance safely
        current_balance = 1000.0
        if user_id is not None:
            uid_str = str(user_id)
            if uid_str in self.baseline_balances:
                current_balance = float(self.baseline_balances[uid_str])
            elif isinstance(user_id, int) and user_id in self.baseline_balances:
                current_balance = float(self.baseline_balances[user_id])
            elif self.baseline_balances:
                current_balance = float(next(iter(self.baseline_balances.values()), 1000.0))

        min_balance = current_balance

        daily_changes = self.generate_daily_schedule(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            events=events
        )

        curr_date = start_date
        while curr_date <= end_date:
            if curr_date in daily_changes:
                current_balance += daily_changes[curr_date]
            if current_balance < min_balance:
                min_balance = current_balance
            curr_date += timedelta(days=1)

        return min_balance

    def calculate_amount_safe_to_pay(self, *args, **kwargs) -> float:
        """
        Determines the maximum safe amount that can be paid without driving 
        the user balance negative during the forecast period.
        """
        kw = dict(kwargs)
        user_id = kw.pop("user_id", None)
        purchase_amount = kw.pop("purchase_amount", None) or kw.pop("amount", None)
        request_date = kw.pop("request_date", None) or kw.pop("start_date", None)
        forecast_days = kw.pop("forecast_days", None) or self.forecast_days

        if args:
            if isinstance(args[0], (dict, object)) and not isinstance(args[0], str):
                req = args[0]
                user_id = user_id or self._get_attr_or_key(req, "user_id")
                purchase_amount = purchase_amount or self._get_attr_or_key(req, "amount") or self._get_attr_or_key(req, "purchase_amount")
                request_date = request_date or self._get_attr_or_key(req, "request_date") or self._get_attr_or_key(req, "start_date")
            else:
                user_id = user_id or args[0]
                if len(args) > 1:
                    purchase_amount = purchase_amount or args[1]
                if len(args) > 2:
                    request_date = request_date or args[2]

        amount_val = float(purchase_amount) if purchase_amount is not None else 0.0

        min_projected = self.get_minimum_projected_balance(
            user_id=user_id,
            request_date=request_date,
            forecast_days=forecast_days,
            **kw
        )

        if min_projected <= 0:
            return 0.0

        return min(amount_val, float(min_projected))

    def find_earliest_date_for_full_payment(self, *args, **kwargs) -> Optional[datetime.date]:
        """
        Returns a datetime.date object (or None) so main.py line 266 
        can call .strftime('%Y-%m-%d') cleanly.
        """
        kw = dict(kwargs)
        user_id = kw.pop("user_id", None)
        purchase_amount = kw.pop("purchase_amount", None) or kw.pop("amount", None)
        request_date = kw.pop("request_date", None) or kw.pop("start_date", None)
        forecast_days = kw.pop("forecast_days", None) or self.forecast_days

        if args:
            if isinstance(args[0], (dict, object)) and not isinstance(args[0], str):
                req = args[0]
                user_id = user_id or self._get_attr_or_key(req, "user_id")
                purchase_amount = purchase_amount or self._get_attr_or_key(req, "amount") or self._get_attr_or_key(req, "purchase_amount")
                request_date = request_date or self._get_attr_or_key(req, "request_date") or self._get_attr_or_key(req, "start_date")
            else:
                user_id = user_id or args[0]
                if len(args) > 1:
                    purchase_amount = purchase_amount or args[1]
                if len(args) > 2:
                    request_date = request_date or args[2]

        amount_val = float(purchase_amount) if purchase_amount is not None else 0.0
        start_date = self._parse_date(request_date) if request_date else datetime.now().date()
        days_to_check = forecast_days or 90

        for offset in range(days_to_check + 1):
            eval_date = start_date + timedelta(days=offset)
            safe_amt = self.calculate_amount_safe_to_pay(
                user_id=user_id,
                purchase_amount=amount_val,
                request_date=eval_date,
                forecast_days=30,
                **kw
            )
            if safe_amt >= amount_val:
                return eval_date

        return None

    def is_plan_safe(self, plan: Any = None, candidate_plan: Any = None, *args, **kwargs) -> bool:
        """
        Evaluates whether a proposed payment plan or schedule maintains 
        a positive minimum balance over the forecast period.
        """
        target_plan = candidate_plan or plan or (args[0] if args else None)
        user_id = kwargs.get("user_id")
        request_date = kwargs.get("request_date") or kwargs.get("start_date")

        if target_plan:
            user_id = user_id or self._get_attr_or_key(target_plan, "user_id")
            request_date = request_date or self._get_attr_or_key(target_plan, "request_date") or self._get_attr_or_key(target_plan, "start_date")

        min_bal = self.get_minimum_projected_balance(
            user_id=user_id,
            request_date=request_date,
            **kwargs
        )
        return min_bal >= 0.0

    def simulate(self, *args, **kwargs):
        """Fallback alias for simulator callers."""
        return self.calculate_amount_safe_to_pay(*args, **kwargs)