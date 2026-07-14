from pathlib import Path

from citations.schema import VerifiedAnswer
from citations.verify import verify_citations
from config.settings import Settings
from generate.pipeline import answer_question
from ingest.vector_index import get_chunk_texts


def answer_with_verified_citations(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> VerifiedAnswer:
    answer = answer_question(question, client, bm25_dir, vector_db_path, settings)
    chunk_texts = get_chunk_texts(vector_db_path, answer.citations) if answer.citations else {}
    return verify_citations(client, question, answer, chunk_texts, settings.citations)
