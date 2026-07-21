from pathlib import Path

import anthropic
import streamlit as st

from citations.pipeline import answer_with_verified_citations
from config import get_settings
from ingest.chunk_metadata import format_citation, load_chunk_metadata

INDEX_DIR = Path("data/index")

st.set_page_config(page_title="Ask My Docs -- FAA Airplane Flying Handbook")
st.title("Ask My Docs")
st.caption(
    "Chat-styled Q&A over the FAA Airplane Flying Handbook (FAA-H-8083-3C) -- "
    "each question is answered independently, not as a multi-turn conversation."
)

if "history" not in st.session_state:
    st.session_state.history = []

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

def _resolve_sources(chunk_ids: list[str]) -> list[str]:
    metadata = load_chunk_metadata(INDEX_DIR / "chunk_metadata.json")
    sources = []
    for chunk_id in chunk_ids:
        try:
            sources.append(format_citation(metadata[chunk_id]))
        except KeyError:
            sources.append(f"{chunk_id} (citation detail unavailable)")
    return sources


def _render_turn(content: str, sources: list[str], low_confidence: bool) -> None:
    st.markdown(content)
    if sources:
        with st.expander("Sources"):
            for source in sources:
                st.markdown(f"- {source}")
    if low_confidence:
        st.warning("Low confidence -- the handbook may not fully cover this question.")


for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        if turn["role"] == "assistant":
            _render_turn(turn["content"], turn.get("sources", []), turn.get("low_confidence", False))
        else:
            st.markdown(turn["content"])

question = st.chat_input("Ask a question about the Airplane Flying Handbook")
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.spinner("Searching the handbook..."):
        result = answer_with_verified_citations(question, client, INDEX_DIR / "bm25", INDEX_DIR / "lancedb", settings)

    sources = _resolve_sources(result.citations) if result.citations else []
    with st.chat_message("assistant"):
        _render_turn(result.answer_text, sources, result.low_confidence)
    st.session_state.history.append(
        {
            "role": "assistant",
            "content": result.answer_text,
            "sources": sources,
            "low_confidence": result.low_confidence,
        }
    )
