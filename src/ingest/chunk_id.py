import hashlib


def make_chunk_id(chapter_number: int, section_title: str, sequence: int) -> str:
    key = f"{chapter_number}|{section_title}|{sequence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
