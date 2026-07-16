from pathlib import Path

import anthropic
import typer

from citations.pipeline import answer_with_verified_citations
from config import get_settings
from ingest.bm25_index import build_bm25_index
from ingest.chunker import chunk_pdf
from ingest.vector_index import build_vector_index
from observability.daily_cost import get_daily_total

app = typer.Typer()


@app.callback()
def callback() -> None:
    # No-op callback keeps Typer in subcommand mode: without it, a single
    # registered command collapses to top-level and "ingest" stops being a
    # named subcommand.
    pass


@app.command()
def ingest(pdf: Path = typer.Option(...), out: Path = typer.Option(...)) -> None:
    settings = get_settings()
    chunks = chunk_pdf(
        pdf,
        min_tokens=settings.chunking.min_tokens,
        max_tokens=settings.chunking.max_tokens,
        overlap_pct=settings.chunking.overlap_pct,
        body_page_start=settings.chunking.body_page_start,
        body_page_end=settings.chunking.body_page_end,
    )
    build_bm25_index(chunks, out / "bm25")
    build_vector_index(chunks, out / "lancedb")
    typer.echo(f"Ingested {len(chunks)} chunks from {pdf} into {out}")


@app.command()
def query(
    question: str = typer.Option(...),
    index: Path = typer.Option(Path("data/index")),
) -> None:
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    result = answer_with_verified_citations(question, client, index / "bm25", index / "lancedb", settings)

    typer.echo(result.answer_text)
    if result.citations:
        typer.echo(f"Citations: {', '.join(result.citations)}")
    flag = " (low confidence)" if result.low_confidence else ""
    typer.echo(f"Coverage: {result.coverage:.2f}{flag}")

    total_cost = get_daily_total(Path(settings.observability.cost_db_path))
    typer.echo(f"Daily cost so far: ${total_cost:.4f}")


if __name__ == "__main__":
    app()
