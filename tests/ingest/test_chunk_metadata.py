import pytest

from ingest.chunk_metadata import ChunkMetadata, format_citation, load_chunk_metadata, write_chunk_metadata


def test_write_then_load_round_trips_metadata(make_chunk, tmp_path):
    chunk = make_chunk("abc123", "some text")
    out_path = tmp_path / "chunk_metadata.json"

    write_chunk_metadata([chunk], out_path)
    loaded = load_chunk_metadata(out_path)

    assert loaded["abc123"] == ChunkMetadata(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        printed_page_label=None,
    )


def test_load_chunk_metadata_raises_key_error_on_unknown_id(make_chunk, tmp_path):
    # Pins the fail-loud contract src/app/streamlit_app.py's _resolve_sources relies on
    # (its `except KeyError:` fallback only fires because this raises, not returns None).
    out_path = tmp_path / "chunk_metadata.json"
    write_chunk_metadata([make_chunk("abc123", "text")], out_path)

    loaded = load_chunk_metadata(out_path)

    with pytest.raises(KeyError):
        loaded["unknown_id"]


def test_format_citation_without_page_label():
    meta = ChunkMetadata(chapter_number=4, chapter_title="Energy Management", section_title="Total Energy")

    assert format_citation(meta) == "Ch. 4: Energy Management — Total Energy"


def test_format_citation_with_page_label():
    meta = ChunkMetadata(
        chapter_number=4, chapter_title="Energy Management", section_title="Total Energy", printed_page_label="4-1"
    )

    assert format_citation(meta) == "Ch. 4: Energy Management — Total Energy, p. 4-1"
