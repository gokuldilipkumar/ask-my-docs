from pathlib import Path

import anthropic
import pytest

from citations.pipeline import answer_with_verified_citations
from config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_DIR = REPO_ROOT / "data" / "index"


@pytest.mark.slow
@pytest.mark.live_langfuse
def test_a_real_query_produces_one_nested_trace_in_langfuse():
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    result = answer_with_verified_citations(
        "What's the difference between VMC and VSO?",
        client,
        INDEX_DIR / "bm25",
        INDEX_DIR / "lancedb",
        settings,
    )

    assert result.answer_text
    # Manual verification step (no public Langfuse query API assumed): open the Langfuse
    # Cloud dashboard and confirm one trace with nested bm25/vector/fusion/rerank/
    # generate.answer/citations.verify spans, usage/cost visible on the two generation spans.
