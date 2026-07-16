from pathlib import Path

import anthropic
import typer

from citations.pipeline import answer_with_verified_citations
from config import get_settings
from eval.baseline import compare_to_baseline, load_latest_baseline
from eval.baseline import save_baseline as save_baseline_run  # avoid shadowing the --save-baseline flag name
from eval.pipeline import run_eval
from eval.schema import load_golden_questions
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


@app.command(name="eval")
def eval_command(
    index: Path = typer.Option(Path("data/index")),
    retrieval_only: bool = typer.Option(False, "--retrieval-only"),
    save_baseline: bool = typer.Option(False, "--save-baseline"),
) -> None:
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    questions = load_golden_questions(Path(settings.eval.golden_path))

    result = run_eval(
        questions, client, index / "bm25", index / "lancedb", settings, retrieval_only=retrieval_only
    )

    exit_code = 0
    baseline = load_latest_baseline(Path(settings.eval.baseline_dir))
    if baseline is None:
        typer.echo("No baseline found -- nothing to compare against.")
    else:
        comparison = compare_to_baseline(result, baseline, settings.eval.tolerance)
        for metric, passed in comparison.items():
            status = "PASS" if passed else "FAIL"
            current_value = getattr(result, metric)
            baseline_value = getattr(baseline, metric)
            typer.echo(f"{metric}: {status} (current={current_value:.3f}, baseline={baseline_value:.3f})")
        if not all(comparison.values()):
            exit_code = 1

    if save_baseline:
        if retrieval_only:
            typer.echo("Skipping baseline save: --retrieval-only runs must not become the tracked baseline.")
        else:
            path = save_baseline_run(result, Path(settings.eval.baseline_dir))
            typer.echo(f"Saved baseline: {path}")

    total_cost = get_daily_total(Path(settings.observability.cost_db_path))
    typer.echo(f"Daily cost so far: ${total_cost:.4f}")

    raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    app()
