from config.settings import Settings
from eval.cache import config_hash, get_cached_result, save_cached_result
from eval.schema import EvalResult


def test_config_hash_changes_when_config_changes():
    settings_a = Settings(anthropic_api_key="x")
    settings_b = Settings(anthropic_api_key="x")
    settings_b.retrieval.top_n = 99

    assert config_hash(settings_a) != config_hash(settings_b)


def test_cache_round_trips_a_result(tmp_path):
    cache_path = tmp_path / "cache.sqlite3"
    result = EvalResult(
        question_id="q1", recall_at_k=1.0, mrr=1.0, ndcg=1.0,
        coverage=1.0, low_confidence=False, correct=True, complete=True,
    )

    assert get_cached_result(cache_path, "q1", "hash-a") is None

    save_cached_result(cache_path, "q1", "hash-a", result)

    cached = get_cached_result(cache_path, "q1", "hash-a")
    assert cached == result


def test_cache_miss_on_different_config_hash(tmp_path):
    cache_path = tmp_path / "cache.sqlite3"
    result = EvalResult(
        question_id="q1", recall_at_k=1.0, mrr=1.0, ndcg=1.0,
        coverage=1.0, low_confidence=False, correct=True, complete=True,
    )
    save_cached_result(cache_path, "q1", "hash-a", result)

    assert get_cached_result(cache_path, "q1", "hash-b") is None
