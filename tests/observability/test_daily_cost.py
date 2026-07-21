from observability.daily_cost import check_budget, format_daily_cost, get_daily_total, record_cost


def test_record_cost_accumulates_same_day_calls(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"

    total = record_cost(db_path, 1.50, day="2026-07-15")
    assert total == 1.50

    total = record_cost(db_path, 0.75, day="2026-07-15")
    assert total == 2.25

    assert get_daily_total(db_path, day="2026-07-15") == 2.25


def test_get_daily_total_is_zero_for_a_day_with_no_recorded_cost(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    assert get_daily_total(db_path, day="2026-07-15") == 0.0


def test_a_new_day_starts_a_fresh_total(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    record_cost(db_path, 4.00, day="2026-07-14")

    assert get_daily_total(db_path, day="2026-07-15") == 0.0
    assert get_daily_total(db_path, day="2026-07-14") == 4.00


def test_check_budget_true_only_once_cap_is_exceeded(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    record_cost(db_path, 4.00, day="2026-07-15")

    assert check_budget(db_path, cap_usd=5.0, day="2026-07-15") is False

    record_cost(db_path, 1.50, day="2026-07-15")

    assert check_budget(db_path, cap_usd=5.0, day="2026-07-15") is True


def test_format_daily_cost_renders_four_decimal_places(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    record_cost(db_path, 0.0421, day="2026-07-15")

    assert format_daily_cost(db_path, day="2026-07-15") == "$0.0421"


def test_format_daily_cost_is_zero_for_a_day_with_no_recorded_cost(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"

    assert format_daily_cost(db_path, day="2026-07-15") == "$0.0000"
