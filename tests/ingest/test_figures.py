from ingest.figures import extract_figure_ref


def test_extracts_figure_number_and_caption():
    ref = extract_figure_ref("Figure 4-3. Forces acting on an airplane in a turn.")
    assert ref is not None
    assert ref.figure_number == "4-3"
    assert ref.caption == "Forces acting on an airplane in a turn."


def test_returns_none_for_non_figure_text():
    assert extract_figure_ref("Total Energy") is None
