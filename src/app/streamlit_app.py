from pathlib import Path

import anthropic
import streamlit as st

from citations.pipeline import answer_with_verified_citations
from config import get_settings

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

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

question = st.chat_input("Ask a question about the Airplane Flying Handbook")
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    result = answer_with_verified_citations(question, client, INDEX_DIR / "bm25", INDEX_DIR / "lancedb", settings)
    with st.chat_message("assistant"):
        st.markdown(result.answer_text)
    st.session_state.history.append({"role": "assistant", "content": result.answer_text})
