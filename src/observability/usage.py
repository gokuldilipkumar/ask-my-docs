import logging
from pathlib import Path

from config.settings import ObservabilityConfig
from observability.cost import calculate_cost
from observability.daily_cost import check_budget, record_cost

logger = logging.getLogger(__name__)


def report_usage(model: str, input_tokens: int, output_tokens: int, config: ObservabilityConfig) -> float:
    """Prices a real API call and records it to the daily running total. Never raises --
    an unpriced model or an over-budget day must not break the caller's real work."""
    try:
        cost = calculate_cost(model, input_tokens, output_tokens, config.price_table)
    except KeyError as e:
        logger.warning(str(e))
        return 0.0

    db_path = Path(config.cost_db_path)
    total = record_cost(db_path, cost)
    if check_budget(db_path, config.daily_cost_cap_usd):
        logger.warning(
            f"Daily cost cap exceeded: ${total:.2f} spent today (cap ${config.daily_cost_cap_usd:.2f})"
        )
    return cost
