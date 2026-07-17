from pathlib import Path

from citations.schema import VerifiedAnswer
from citations.verify import verify_citations
from config.settings import Settings
from generate.pipeline import answer_question
from ingest.vector_index import get_chunk_texts
from observability.context import ObservabilityContext
from observability.langfuse_tracer import get_tracer


def answer_with_verified_citations(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> VerifiedAnswer:
    observability = ObservabilityContext(tracer=get_tracer(settings), config=settings.observability)
    # Wraps the whole call chain in one parent span -- Langfuse/OTel nesting requires a
    # child span to open while its parent's context is still active, so without this the
    # retrieval/rerank/generate/verify spans below each became their own separate root
    # trace instead of nesting under one trace per query (found via a real trace screenshot).
    with observability.tracer.span("query.answer_with_verified_citations"):
        answer = answer_question(question, client, bm25_dir, vector_db_path, settings, observability=observability)
        chunk_texts = get_chunk_texts(vector_db_path, answer.citations) if answer.citations else {}
        return verify_citations(
            client, question, answer, chunk_texts, settings.citations, observability=observability
        )
