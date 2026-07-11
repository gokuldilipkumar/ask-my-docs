import re

from ingest.models import FigureRef

FIGURE_PATTERN = re.compile(r"^Figure (\d+-\d+)\.\s+(.+)$")


def extract_figure_ref(text: str) -> FigureRef | None:
    match = FIGURE_PATTERN.match(text)
    if not match:
        return None
    return FigureRef(figure_number=match.group(1), caption=match.group(2))
