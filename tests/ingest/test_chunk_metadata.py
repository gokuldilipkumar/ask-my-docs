from ingest.chunk_metadata import ChunkMetadata, load_chunk_metadata, write_chunk_metadata


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


def test_load_chunk_metadata_raises_on_unknown_id(make_chunk, tmp_path):
    out_path = tmp_path / "chunk_metadata.json"
    write_chunk_metadata([make_chunk("abc123", "text")], out_path)

    loaded = load_chunk_metadata(out_path)

    assert "unknown_id" not in loaded
