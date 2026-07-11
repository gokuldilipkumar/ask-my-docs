from ingest.tokens import count_tokens


def test_counts_tokens_for_short_text():
    assert count_tokens("Hello world") > 0


def test_longer_text_has_more_tokens_than_shorter_text():
    short = count_tokens("Energy management.")
    long = count_tokens("Energy management is the demonstrated ability to control total energy.")
    assert long > short
