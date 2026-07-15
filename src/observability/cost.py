def calculate_cost(
    model: str, input_tokens: int, output_tokens: int, price_table: dict[str, dict[str, float]]
) -> float:
    if model not in price_table:
        raise KeyError(f"No price entry for model '{model}' in observability.price_table")
    prices = price_table[model]
    return (input_tokens * prices["input_per_million"] + output_tokens * prices["output_per_million"]) / 1_000_000
