"""Knowledge assistant API (Phase 7): answers with sources, "not covered", the document and
section viewers, the copilot's knowledge questions, and pgvector search where it is installed.

A hashed bag-of-words embedder stands in for the MiniLM model (no download)."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ai.embeddings.embedder import HashEmbedder
from ai.nlp.intent_parser import RuleParser
from ai.rag.ingest import load_chunks
from ai.rag.pipeline import KnowledgeBase, Settings
from ai.rag.retriever import Retriever
from ai.rag.store import PgVectorIndex, ingest, pgvector_ready
from app.core.config import get_settings
from app.main import app
from app.services.copilot import copilot
from app.services.knowledge import knowledge

API = "/api/v1/rag"
OVERHEATING = "overheating robot pause it at the next safe stop and reassign its order"


@pytest.fixture(scope="module")
def chunks():
    return load_chunks("section")


@pytest.fixture()
def client(chunks):
    original = knowledge.kb
    # Dense scores (cosine) measure relevance; hybrid's fused rank score would not.
    retriever = Retriever(chunks, HashEmbedder(), mode="dense")
    knowledge.kb = KnowledgeBase(chunks, retriever, Settings(retriever="dense", threshold=0.3))
    yield TestClient(app)  # no context manager: the simulator loop stays off
    knowledge.kb = original


def test_status_describes_the_loaded_knowledge_base(client, chunks):
    from ai.rag.ingest import DOC_ORDER

    body = client.get(f"{API}/status").json()
    assert body["loaded"] and body["documents"] == len(DOC_ORDER) == 7
    assert body["chunks"] == len(chunks) > 170
    assert body["store"] == "memory" and body["generator"].startswith("extractive")


def test_query_answers_with_cited_sources(client):
    body = client.post(f"{API}/query", json={"question": OVERHEATING}).json()
    assert body["covered"] and body["sources"][0]["section_id"] == "SOP-04"
    assert "[SOP-04]" in body["answer"]
    filtered = client.post(f"{API}/query", json={"question": "robot", "doc_type": "safety"})
    assert {s["doc_type"] for s in filtered.json()["sources"]} == {"safety"}


def test_unrelated_questions_are_not_covered_but_show_the_closest_passages(client):
    body = client.post(f"{API}/query", json={"question": "zebra quantum violin"}).json()
    assert not body["covered"] and "do not cover" in body["answer"] and body["sources"]


def test_input_is_validated(client):
    assert client.post(f"{API}/query", json={"question": "hi"}).status_code == 422
    bad_type = client.post(f"{API}/query", json={"question": "robots", "doc_type": "x"})
    assert bad_type.status_code == 422


def test_document_and_section_viewer(client, chunks):
    docs = client.get(f"{API}/documents").json()
    assert [d["doc_id"] for d in docs][0] == "warehouse_manual"
    assert docs[-1]["doc_id"] == "shipping_policies"
    assert sum(len(d["sections"]) for d in docs) == len(chunks)
    section = client.get(f"{API}/sections/SOP-04").json()
    assert section["heading"] == "Overheating robot" and "60 C" in section["text"]
    assert client.get(f"{API}/sections/XX-9").status_code == 404


def test_copilot_knowledge_questions_are_answered_from_the_documents(client):
    original = copilot.parser
    copilot.parser = RuleParser()
    try:
        reply = client.post(
            "/api/v1/copilot/chat", json={"text": "what does the SOP say about overheating?"}
        ).json()
    finally:
        copilot.parser = original
    assert reply["understanding"]["intent"] == "knowledge_query"
    assert reply["data"]["knowledge"]["sources"] and reply["answer"]


def _database_with_pgvector():
    try:
        engine = create_engine(get_settings().database_url)
        return engine if pgvector_ready(engine) else None
    except Exception:
        return None


def test_pgvector_search_ranks_like_memory(chunks):
    engine = _database_with_pgvector()
    if engine is None:
        pytest.skip("no PostgreSQL with pgvector (migration 003) available")
    embedder = HashEmbedder(dim=384)  # warehouse_docs stores 384-dim vectors
    vectors = embedder.encode([c.for_embedding() for c in chunks])
    with engine.connect() as conn, conn.begin() as tx:  # rolled back: stored docs untouched
        ingest(conn, chunks, vectors)
        index = PgVectorIndex(conn, chunks)
        query = embedder.encode([OVERHEATING])[0]
        in_db = index.cosines(query, limit=10)
        in_memory = vectors @ query
        top_db = [int(i) for i in np.argsort(-in_db)[:5]]
        assert top_db == [int(i) for i in np.argsort(-in_memory)[:5]]
        assert np.allclose(in_db[top_db], in_memory[top_db], atol=1e-4)
        tx.rollback()
