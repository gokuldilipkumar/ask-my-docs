from ingest.chunk_id import make_chunk_id


def test_same_inputs_produce_same_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    assert id1 == id2


def test_different_sequence_produces_different_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=1)
    assert id1 != id2


def test_different_section_title_produces_different_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Kinetic Energy", sequence=0)
    assert id1 != id2
