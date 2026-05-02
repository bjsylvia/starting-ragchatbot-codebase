"""End-to-end tests for RAGSystem.query().

VectorStore is swapped for FakeVectorStore (avoids ChromaDB + sentence-transformers).
AnthropicClient is scripted.
"""
import pytest
from types import SimpleNamespace

from tests.conftest import text_response, tool_use_response, empty_response


class _FakeConfig:
    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 100
    CHROMA_PATH = "/tmp/unused"
    EMBEDDING_MODEL = "unused"
    MAX_RESULTS = 5
    MAX_HISTORY = 2
    ANTHROPIC_API_KEY = "sk-test"
    ANTHROPIC_MODEL = "claude-test"


@pytest.fixture
def rag_system(monkeypatch, fake_store, scripted_anthropic):
    """Build a real RAGSystem with VectorStore swapped for fake_store.
    Anthropic is *not* scripted here — each test does that itself."""
    import rag_system as rag_module

    monkeypatch.setattr(rag_module, "VectorStore", lambda *a, **kw: fake_store)

    # Swap DocumentProcessor too (avoids any side-effects on init)
    monkeypatch.setattr(rag_module, "DocumentProcessor", lambda *a, **kw: SimpleNamespace())

    # Install no-op Anthropic so __init__ doesn't crash; real scripting
    # happens in each test via scripted_anthropic.
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=SimpleNamespace(create=lambda **k: None)))

    return rag_module.RAGSystem(_FakeConfig())


def test_content_query_happy_path(rag_system, fake_store, scripted_anthropic):
    fake_store.queue_results(
        documents=["Reranking uses cross-encoders."],
        metadata=[{"course_title": "Advanced Retrieval", "lesson_number": 4}],
    )
    fake_store.lesson_links[("Advanced Retrieval", 4)] = "https://example.com/l4"

    # Replace the generator's client with a scripted one.
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "reranking"}),
        text_response("Reranking uses a cross-encoder to reorder results."),
    ])
    rag_system.ai_generator.client = client

    answer, sources = rag_system.query("What does Chroma teach about reranking?")

    assert answer == "Reranking uses a cross-encoder to reorder results."
    assert sources == [{"text": "Advanced Retrieval - Lesson 4", "link": "https://example.com/l4"}]


def test_general_knowledge_query_has_empty_sources(rag_system, fake_store, scripted_anthropic):
    client = scripted_anthropic([text_response("2 + 2 = 4.")])
    rag_system.ai_generator.client = client

    answer, sources = rag_system.query("What is 2+2?")

    assert answer == "2 + 2 = 4."
    assert sources == []


def test_sources_reset_between_queries(rag_system, fake_store, scripted_anthropic):
    # First query populates sources via the search tool.
    fake_store.queue_results(
        documents=["d1"], metadata=[{"course_title": "C", "lesson_number": 1}]
    )
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}),
        text_response("a1"),
        # Second query — general knowledge, no tool_use.
        text_response("a2"),
    ])
    rag_system.ai_generator.client = client

    _, src1 = rag_system.query("q1")
    assert src1 != []

    _, src2 = rag_system.query("q2")
    assert src2 == [], "sources must reset after each query"


def test_session_history_flows_into_system_prompt(rag_system, scripted_anthropic):
    client = scripted_anthropic([text_response("a1"), text_response("a2")])
    rag_system.ai_generator.client = client

    sid = rag_system.session_manager.create_session()
    rag_system.query("first question", session_id=sid)
    rag_system.query("second question", session_id=sid)

    second_system = client.calls[1]["system"]
    assert "Previous conversation:" in second_system
    assert "first question" in second_system
    assert "a1" in second_system


def test_tool_exception_is_reported_to_claude_not_bubbled(
    rag_system, fake_store, scripted_anthropic
):
    """Fix A: a tool exception is converted to a 'Tool error' result the
    model can react to, instead of bubbling a 500 to FastAPI. This
    eliminates the 'query failed' symptom for content queries when
    ChromaDB / sentence-transformers / HF mirror hiccup."""
    fake_store.search_raises = RuntimeError("chromadb exploded")
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}),
        text_response("I couldn't search course materials just now."),
    ])
    rag_system.ai_generator.client = client

    answer, sources = rag_system.query("content question")
    assert answer == "I couldn't search course materials just now."
    assert sources == []


def test_outline_tool_sources_flow_through(rag_system, fake_store, scripted_anthropic):
    """F3 regression: outline-tool sources must also surface via ToolManager.get_last_sources."""
    fake_store.seed_course(
        "MCP: Build Rich-Context AI Apps with Anthropic",
        "https://example.com/mcp",
        lessons=[
            {"lesson_number": 0, "lesson_title": "Intro", "lesson_link": None},
            {"lesson_number": 1, "lesson_title": "Why MCP", "lesson_link": None},
        ],
    )
    client = scripted_anthropic([
        tool_use_response("get_course_outline", {"course_name": "MCP"}),
        text_response("MCP is..."),
    ])
    rag_system.ai_generator.client = client

    _, sources = rag_system.query("What lessons are in the MCP course?")
    assert len(sources) == 1
    assert sources[0]["text"] == "MCP: Build Rich-Context AI Apps with Anthropic"
    assert sources[0]["link"] == "https://example.com/mcp"


def test_unregistered_tool_does_not_raise(rag_system, scripted_anthropic):
    """If the model calls a tool that doesn't exist, ToolManager returns a
    'not found' string and the generator recovers on the second hop."""
    client = scripted_anthropic([
        tool_use_response("bogus_tool", {}),
        text_response("recovered"),
    ])
    rag_system.ai_generator.client = client

    answer, _ = rag_system.query("something")
    assert answer == "recovered"


def test_api_final_response_empty_content_returns_empty_answer(
    rag_system, fake_store, scripted_anthropic
):
    """Fix A: if the second Anthropic call returns empty content (content=[]),
    the generator returns an empty string rather than crashing with IndexError."""
    fake_store.queue_results(
        documents=["d"], metadata=[{"course_title": "C", "lesson_number": 1}]
    )
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}),
        empty_response(),
    ])
    rag_system.ai_generator.client = client

    answer, sources = rag_system.query("content question")
    assert answer == ""
    # Sources are still surfaced — the tool did run successfully.
    assert sources == [{"text": "C - Lesson 1", "link": None}]


def test_rag_level_exception_is_caught_and_reported_gracefully(
    rag_system, fake_store, scripted_anthropic, monkeypatch
):
    """Fix B: if something below generate_response raises unexpectedly
    (e.g. Anthropic SDK auth/rate-limit), RAGSystem.query returns a
    graceful ('error', []) tuple instead of letting the exception reach
    FastAPI as a 500."""
    # Force an exception at the generator boundary
    def _boom(**kwargs):
        raise RuntimeError("anthropic 500")

    monkeypatch.setattr(rag_system.ai_generator, "generate_response", _boom)

    answer, sources = rag_system.query("whatever")
    assert "went wrong" in answer.lower() or "error" in answer.lower()
    assert "anthropic 500" in answer
    assert sources == []
