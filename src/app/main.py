from pathlib import Path

import typer

from config import get_settings
from ingest.bm25_index import build_bm25_index
from ingest.chunker import chunk_pdf
from ingest.vector_index import build_vector_index

app = typer.Typer()


@app.callback()
def callback() -> None:
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


if __name__ == "__main__":
    app()
