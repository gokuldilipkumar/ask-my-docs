import json
from pathlib import Path

from pydantic import BaseModel

from ingest.models import Chunk


class ChunkMetadata(BaseModel):
    chapter_number: int
    chapter_title: str
    section_title: str
    printed_page_label: str | None = None


def write_chunk_metadata(chunks: list[Chunk], out_path: Path) -> None:
    payload = {
        c.chunk_id: ChunkMetadata(
            chapter_number=c.chapter_number,
            chapter_title=c.chapter_title,
            section_title=c.section_title,
            printed_page_label=c.printed_page_label,
        ).model_dump()
        for c in chunks
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload))


def load_chunk_metadata(path: Path) -> dict[str, ChunkMetadata]:
    raw = json.loads(path.read_text())
    return {chunk_id: ChunkMetadata(**fields) for chunk_id, fields in raw.items()}


def format_citation(meta: ChunkMetadata) -> str:
    page = f", p. {meta.printed_page_label}" if meta.printed_page_label else ""
    return f"Ch. {meta.chapter_number}: {meta.chapter_title} — {meta.section_title}{page}"
