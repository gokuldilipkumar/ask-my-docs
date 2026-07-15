import logging

from config.settings import ObservabilityConfig
from observability.daily_cost import get_daily_total
from observability.usage import report_usage

PRICE_TABLE = {"fake-model": {"input_per_million": 3.0, "output_per_million": 15.0}}


def test_report_usage_records_cost_to_the_daily_total(tmp_path):
    config = ObservabilityConfig(
        cost_db_path=str(tmp_path / "daily_cost.sqlite3"), price_table=PRICE_TABLE, daily_cost_cap_usd=100.0
    )

    cost = report_usage("fake-model", input_tokens=1_000_000, output_tokens=0, config=config)

    assert cost == 3.0
    assert get_daily_total(tmp_path / "daily_cost.sqlite3") == 3.0


def test_report_usage_warns_and_returns_zero_for_an_unpriced_model(tmp_path, caplog):
    config = ObservabilityConfig(cost_db_path=str(tmp_path / "daily_cost.sqlite3"), price_table={})

    with caplog.at_level(logging.WARNING):
        cost = report_usage("unpriced-model", input_tokens=100, output_tokens=100, config=config)

    assert cost == 0.0
    assert "unpriced-model" in caplog.text


def test_report_usage_warns_without_raising_when_daily_cap_exceeded(tmp_path, caplog):
    config = ObservabilityConfig(
        cost_db_path=str(tmp_path / "daily_cost.sqlite3"), price_table=PRICE_TABLE, daily_cost_cap_usd=1.0
    )

    with caplog.at_level(logging.WARNING):
        cost = report_usage("fake-model", input_tokens=1_000_000, output_tokens=0, config=config)

    assert cost == 3.0  # the call that pushed spend over the cap still succeeds and returns its real cost
    assert "cap" in caplog.text.lower()
