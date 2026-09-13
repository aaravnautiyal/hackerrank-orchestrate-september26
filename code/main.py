"""
Main Pipeline Orchestrator for Buy or Wait? Autonomous Financial AI Engine.
Reads CSV datasets, processes perceptions, runs cashflow engine, ranks plans, and outputs predictions.
"""

import os
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional

from code.credentials import CredentialsManager
from code.extractor import PerceptionExtractor
from code.ranker import DecisionRanker
from code.schema import (
    AffordabilityStatus,
    CashflowEvent,
    DecisionOutput,
    FlexibleOption,
    Frequency,
    PaymentMethod,
    PurchaseRequest,
    SpendingChangeItem,
    UserProfile,
)
from code.simulator import CashflowSimulator
from code.tracker import TokenTracker


def parse_date(date_val) -> Optional[date]:
    """Safely parses date strings, returning None for missing or invalid dates."""
    if pd.isna(date_val) or date_val is None or str(date_val).strip().lower() in ("none", "nan", "", "nat"):
        return None
    
    clean_str = str(date_val).strip().split(" ")[0]  # Strip time component if present
    try:
        return datetime.strptime(clean_str, "%Y-%m-%d").date()
    except ValueError:
        try:
            return pd.to_datetime(clean_str).date()
        except Exception:
            return None


def get_column_value(row: pd.Series, candidates: List[str], default=None):
    """Helper function to fetch values across potential column name variations."""
    for col in candidates:
        if col in row.index and pd.notna(row[col]):
            return row[col]
    return default


def run_pipeline(dataset_dir: str = "dataset", output_csv_path: str = "output.csv"):
    tracker = TokenTracker()
    tracker.log_agent_turn("Orchestrator", "INIT", "Initializing Buy or Wait Autonomous Pipeline.")

    # 1. Load Datasets
    profiles_df = pd.read_csv(os.path.join(dataset_dir, "financial_profiles.csv"))
    events_df = pd.read_csv(os.path.join(dataset_dir, "financial_events.csv"))
    requests_df = pd.read_csv(os.path.join(dataset_dir, "requests.csv"))
    options_df = pd.read_csv(os.path.join(dataset_dir, "request_payment_options.csv"))
    exchange_df = pd.read_csv(os.path.join(dataset_dir, "exchange_rates.csv"))

    messages_df = (
        pd.read_csv(os.path.join(dataset_dir, "messages.csv"))
        if os.path.exists(os.path.join(dataset_dir, "messages.csv"))
        else None
    )

    # Build exchange rate lookup dictionary
    exchange_rates: Dict[Tuple[str, str], float] = {}
    for _, row in exchange_df.iterrows():
        from_curr = get_column_value(row, ["from_currency", "source_currency", "currency_from"])
        to_curr = get_column_value(row, ["to_currency", "target_currency", "currency_to"])
        rate = get_column_value(row, ["rate", "exchange_rate", "conversion_rate"])
        if from_curr and to_curr and rate is not None:
            exchange_rates[(str(from_curr), str(to_curr))] = float(rate)

    # Initialize Perception Extractor & Cashflow Engine
    extractor = PerceptionExtractor()
    simulator = CashflowSimulator(forecast_days=90)
    ranker = DecisionRanker(simulator=simulator)

    outputs: List[DecisionOutput] = []

    # Process each purchase request
    for _, req_row in requests_df.iterrows():
        req_id = str(get_column_value(req_row, ["request_id", "id"]))
        user_id = str(get_column_value(req_row, ["user_id", "uid"]))
        
        req_date_val = get_column_value(req_row, ["request_date", "date", "created_at"])
        req_date = parse_date(req_date_val) or date.today()

        # Target column is requested_amount in your dataset schema
        raw_amount = get_column_value(
            req_row, 
            ["requested_amount", "total_amount", "amount", "request_amount", "item_cost", "price", "cost"]
        )
        
        if raw_amount is None:
            for col in req_row.index:
                if "id" not in col.lower() and "date" not in col.lower() and "currency" not in col.lower() and "text" not in col.lower():
                    try:
                        raw_amount = float(req_row[col])
                        break
                    except (ValueError, TypeError):
                        continue

        if raw_amount is None:
            raise KeyError(f"Could not parse amount from request columns: {req_row.index.tolist()}")

        total_amount = float(raw_amount)
        currency = str(get_column_value(req_row, ["currency", "curr"], default="USD"))

        desired_comp_val = get_column_value(req_row, ["desired_completion_date", "target_date"])
        desired_comp_date = parse_date(desired_comp_val)

        request = PurchaseRequest(
            request_id=req_id,
            user_id=user_id,
            request_date=req_date,
            item_category=str(get_column_value(req_row, ["request_type", "item_category", "category"], default="general")),
            total_amount=total_amount,
            currency=currency,
            desired_completion_date=desired_comp_date,
        )

        # Get user profile
        user_prof_rows = profiles_df[profiles_df["user_id"] == user_id]
        if not user_prof_rows.empty:
            user_prof_row = user_prof_rows.iloc[0]
            home_currency = str(get_column_value(user_prof_row, ["home_currency", "currency"], default="USD"))
            min_bal = float(get_column_value(user_prof_row, ["minimum_balance_to_keep", "min_balance"], default=0.0))
            initial_balance = float(
                get_column_value(user_prof_row, ["starting_balance", "initial_balance", "current_balance", "balance"], default=0.0)
            )
        else:
            home_currency = "USD"
            min_bal = 0.0
            initial_balance = 0.0

        profile = UserProfile(
            user_id=user_id,
            home_currency=home_currency,
            minimum_balance_to_keep=min_bal,
        )

        # Build list of cashflow events for this user
        user_events_df = events_df[events_df["user_id"] == user_id]
        events: List[CashflowEvent] = []
        for _, evt_row in user_events_df.iterrows():
            evt_start = parse_date(get_column_value(evt_row, ["start_date", "date", "event_date", "created_at"]))
            if evt_start is None:
                evt_start = req_date  # Fallback to request date if start date is missing

            events.append(
                CashflowEvent(
                    event_id=str(get_column_value(evt_row, ["event_id", "id"])),
                    user_id=user_id,
                    type=str(get_column_value(evt_row, ["type", "event_type"], default="expense")),
                    category=str(get_column_value(evt_row, ["category"], default="general")),
                    amount=float(get_column_value(evt_row, ["amount", "value"], default=0.0)),
                    currency=str(get_column_value(evt_row, ["currency"], default=profile.home_currency)),
                    frequency=Frequency(str(get_column_value(evt_row, ["frequency"], default="once")).lower()),
                    start_date=evt_start,
                    end_date=parse_date(get_column_value(evt_row, ["end_date"])),
                    is_flexible=bool(get_column_value(evt_row, ["is_flexible", "flexible"], default=False)),
                )
            )

        # Stage 1: Multimodal Perception & Message Sanitization
        spending_overrides: Dict[str, float] = {}
        cancelled_events = set()

        if messages_df is not None:
            user_messages = messages_df[messages_df["user_id"] == user_id]
            for _, msg_row in user_messages.iterrows():
                msg_text = str(get_column_value(msg_row, ["message_text", "text", "message"]))
                target_evt_id = str(get_column_value(msg_row, ["event_id", "target_id"]))

                tracker.log_agent_turn("PerceptionExtractor", "PARSE_MSG", f"Parsing msg for event {target_evt_id}")
                extraction = extractor.extract_message_updates(msg_text, target_evt_id)

                tracker.record_llm_call(
                    provider="Groq",
                    model_name=extractor.text_model,
                    input_tokens=150,
                    output_tokens=50,
                    purpose=f"Message parsing for event {target_evt_id}",
                    estimated_cost=0.00005,
                )

                if extraction.is_cancelled:
                    cancelled_events.add(target_evt_id)
                elif extraction.new_flexible_amount is not None:
                    spending_overrides[target_evt_id] = extraction.new_flexible_amount

        # Stage 2: Deterministic Daily Net Cashflow Calculation
        forecast_end = req_date + pd.Timedelta(days=90)
        daily_net = simulator.generate_daily_schedule(
            events=events,
            start_date=req_date,
            end_date=forecast_end,
            home_currency=profile.home_currency,
            exchange_rates=exchange_rates,
            spending_overrides=spending_overrides,
            cancelled_events=cancelled_events,
        )

        # Calculate maximum safe lump-sum payment on request_date
        amount_safe = simulator.calculate_amount_safe_to_pay(
            initial_balance=initial_balance,
            profile=profile,
            request_date=req_date,
            daily_net=daily_net,
            max_amount=request.total_amount,
        )

        earliest_full_date = simulator.find_earliest_date_for_full_payment(
            initial_balance=initial_balance,
            profile=profile,
            request_date=req_date,
            daily_net=daily_net,
            full_amount=request.total_amount,
        )

        # Stage 3: Candidate Plan Generator & 6-Tier Ranking
        req_options_df = options_df[options_df["request_id"] == req_id]
        candidates = []

        for _, opt_row in req_options_df.iterrows():
            opt = FlexibleOption(
                option_id=str(get_column_value(opt_row, ["option_id", "id"])),
                request_id=req_id,
                payment_method=PaymentMethod(str(get_column_value(opt_row, ["payment_method", "method"])).lower()),
                down_payment=float(get_column_value(opt_row, ["down_payment"], default=0.0)),
                installment_amount=float(get_column_value(opt_row, ["installment_amount"], default=0.0)),
                num_installments=int(get_column_value(opt_row, ["num_installments"], default=1)),
                installment_frequency_days=int(get_column_value(opt_row, ["installment_frequency_days"], default=30)),
                fee_amount=float(get_column_value(opt_row, ["fee_amount", "fee"], default=0.0)),
            )

            candidate = ranker.evaluate_candidate_plan(
                option=opt,
                request=request,
                profile=profile,
                initial_balance=initial_balance,
                daily_net=daily_net,
            )
            candidates.append(candidate)

        best_plan = ranker.rank_candidates(candidates)
        affordability_status = ranker.determine_affordability_status(best_plan, amount_safe, request)

        # Format output fields
        rec_method = (
            best_plan.recommended_payment_method
            if best_plan
            else PaymentMethod.NOT_RECOMMENDED
        )

        plan_str = "none"
        if best_plan and best_plan.payment_plan:
            plan_str = "|".join([item.to_str() for item in best_plan.payment_plan])

        earliest_date_str = (
            earliest_full_date.strftime("%Y-%m-%d") if earliest_full_date else "none"
        )

        spending_changes_str = "none"
        if best_plan and best_plan.spending_changes:
            spending_changes_str = "|".join([item.to_str() for item in best_plan.spending_changes])

        explanation = (
            f"Evaluated 90-day forecast. Safe immediate payment: ${amount_safe:.2f}. "
            f"Selected plan '{rec_method.value}' adhering to minimum balance constraint ${profile.minimum_balance_to_keep:.2f}."
        )

        outputs.append(
            DecisionOutput(
                request_id=req_id,
                amount_safe_to_pay=amount_safe,
                affordability_status=affordability_status,
                recommended_payment_method=rec_method,
                payment_plan=plan_str,
                earliest_date_for_full_payment=earliest_date_str,
                spending_changes_needed=spending_changes_str,
                decision_explanation=explanation,
            )
        )

    # Save exact schema to output.csv
    output_df = pd.DataFrame([out.model_dump() for out in outputs])
    output_df.to_csv(output_csv_path, index=False)

    tracker.generate_usage_report()
    tracker.log_agent_turn("Orchestrator", "COMPLETE", f"Pipeline completed. Written to {output_csv_path}")
    print(f"Pipeline executed successfully. Outputs saved to {output_csv_path}")


if __name__ == "__main__":
    run_pipeline()