from datetime import date
from schema import UserProfile, CashflowEvent, Frequency
from simulator import CashflowSimulator

profile = UserProfile(user_id="u1", home_currency="USD", minimum_balance_to_keep=1000.0)
sim = CashflowSimulator(forecast_days=90)

events = [
    CashflowEvent(
        event_id="e1", user_id="u1", type="inflow", category="salary",
        amount=3000.0, currency="USD", frequency=Frequency.MONTHLY,
        start_date=date(2026, 9, 15)
    ),
    CashflowEvent(
        event_id="e2", user_id="u1", type="outflow", category="rent",
        amount=1200.0, currency="USD", frequency=Frequency.MONTHLY,
        start_date=date(2026, 9, 1)
    )
]

daily_net = sim.generate_daily_schedule(
    events=events, start_date=date(2026, 9, 13), end_date=date(2026, 12, 12),
    home_currency="USD", exchange_rates={}
)

safe_amt = sim.calculate_amount_safe_to_pay(
    initial_balance=1500.0, profile=profile, request_date=date(2026, 9, 13),
    daily_net=daily_net, max_amount=2000.0
)

print(f"Safe Immediate Amount: ${safe_amt:.2f}")