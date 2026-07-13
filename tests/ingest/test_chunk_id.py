from ingest.chunk_id import make_chunk_id


def test_same_inputs_produce_same_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", page_index_start=60, sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Total Energy", page_index_start=60, sequence=0)
    assert id1 == id2


def test_different_sequence_produces_different_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", page_index_start=60, sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Total Energy", page_index_start=60, sequence=1)
    assert id1 != id2


def test_different_section_title_produces_different_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", page_index_start=60, sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Kinetic Energy", page_index_start=60, sequence=0)
    assert id1 != id2


def test_same_title_and_sequence_on_different_pages_produce_different_ids():
    # the handbook repeats section titles within a chapter ("Common errors...",
    # once per maneuver) — start page disambiguates them
    id1 = make_chunk_id(chapter_number=5, section_title="Common Errors", page_index_start=90, sequence=0)
    id2 = make_chunk_id(chapter_number=5, section_title="Common Errors", page_index_start=97, sequence=0)
    assert id1 != id2
