import pytest

from observability.cost import calculate_cost

PRICE_TABLE = {"fake-model": {"input_per_million": 3.0, "output_per_million": 15.0}}


def test_calculate_cost_prices_input_and_output_tokens_independently():
    cost = calculate_cost("fake-model", input_tokens=1_000_000, output_tokens=0, price_table=PRICE_TABLE)
    assert cost == pytest.approx(3.0)

    cost = calculate_cost("fake-model", input_tokens=0, output_tokens=1_000_000, price_table=PRICE_TABLE)
    assert cost == pytest.approx(15.0)


def test_calculate_cost_raises_on_unpriced_model():
    with pytest.raises(KeyError, match="fake-model"):
        calculate_cost("fake-model", input_tokens=100, output_tokens=100, price_table={})
