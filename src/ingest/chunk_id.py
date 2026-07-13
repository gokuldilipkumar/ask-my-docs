import hashlib


def make_chunk_id(
    chapter_number: int, section_title: str, page_index_start: int, sequence: int
) -> str:
    # page_index_start disambiguates identically-titled sections within a chapter
    # (the handbook repeats titles like "Common Errors" once per maneuver); it is
    # stable across re-ingestion for a fixed PDF, unlike an occurrence counter,
    # which would shift whenever header detection changes earlier in the chapter
    key = f"{chapter_number}|{section_title}|{page_index_start}|{sequence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
