"""Exercises AIGenerator.generate_response() with a mocked Anthropic client.

Tool-calling path = two-hop: first Claude call may return stop_reason='tool_use',
then the generator runs the tool and makes a second call without tools to get
the final text.
"""
import pytest

from ai_generator import AIGenerator
from search_tools import CourseSearchTool, ToolManager
from tests.conftest import text_response, tool_use_response, empty_response


@pytest.fixture
def tool_manager(fake_store):
    mgr = ToolManager()
    mgr.register_tool(CourseSearchTool(fake_store))
    return mgr


def _make_generator():
    return AIGenerator(api_key="sk-test", model="claude-test")


def test_no_tool_path_returns_text(scripted_anthropic):
    client = scripted_anthropic([text_response("2 + 2 = 4.")])
    gen = _make_generator()
    out = gen.generate_response("What is 2+2?")
    assert out == "2 + 2 = 4."
    assert len(client.calls) == 1
    assert "tools" not in client.calls[0]


def test_tools_passed_but_not_used(scripted_anthropic, tool_manager):
    client = scripted_anthropic([text_response("4")])
    gen = _make_generator()
    out = gen.generate_response(
        "What is 2+2?",
        tools=tool_manager.get_tool_definitions(),
        tool_manager=tool_manager,
    )
    assert out == "4"
    assert len(client.calls) == 1
    assert client.calls[0]["tools"] == tool_manager.get_tool_definitions()
    assert client.calls[0]["tool_choice"] == {"type": "auto"}


def test_tool_use_path_two_hops(scripted_anthropic, tool_manager, fake_store):
    fake_store.queue_results(
        documents=["Reranking uses cross-encoders."],
        metadata=[{"course_title": "Advanced Retrieval", "lesson_number": 4}],
    )
    fake_store.lesson_links[("Advanced Retrieval", 4)] = "https://example.com/l4"

    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "reranking"}),
        text_response("Reranking reorders results with a cross-encoder."),
    ])
    gen = _make_generator()

    out = gen.generate_response(
        "What does Chroma teach about reranking?",
        tools=tool_manager.get_tool_definitions(),
        tool_manager=tool_manager,
    )

    assert out == "Reranking reorders results with a cross-encoder."
    assert len(client.calls) == 2
    # Second call must have no tools (ai_generator.py:130-134)
    assert "tools" not in client.calls[1]
    # Second call's messages carry the tool_use + tool_result pair
    messages = client.calls[1]["messages"]
    assert messages[-1]["role"] == "user"
    tool_result_block = messages[-1]["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert "Reranking uses cross-encoders." in tool_result_block["content"]
    # FakeVectorStore saw the tool's search call
    assert fake_store.search_calls and fake_store.search_calls[0]["query"] == "reranking"


def test_tool_use_then_sources_populated(scripted_anthropic, tool_manager, fake_store):
    fake_store.queue_results(
        documents=["d"],
        metadata=[{"course_title": "C", "lesson_number": 1}],
    )
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}),
        text_response("final"),
    ])
    gen = _make_generator()
    gen.generate_response(
        "q",
        tools=tool_manager.get_tool_definitions(),
        tool_manager=tool_manager,
    )
    assert tool_manager.get_last_sources() == [{"text": "C - Lesson 1", "link": None}]


def test_unknown_tool_returns_not_found_string_not_exception(
    scripted_anthropic, tool_manager
):
    client = scripted_anthropic([
        tool_use_response("nonexistent_tool", {"x": 1}),
        text_response("ok"),
    ])
    gen = _make_generator()
    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )
    assert out == "ok"
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert "not found" in tool_result["content"].lower()


def test_tool_raising_is_converted_to_tool_error_string(
    scripted_anthropic, tool_manager, fake_store
):
    """Fix A: a tool exception is caught and reported to Claude as a
    tool_result with 'Tool error: ...', then the generator continues."""
    fake_store.search_raises = RuntimeError("chromadb exploded")
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}),
        text_response("I couldn't look that up."),
    ])
    gen = _make_generator()
    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )
    assert out == "I couldn't look that up."
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "Tool error" in tool_result["content"]
    assert "chromadb exploded" in tool_result["content"]


def test_empty_final_content_returns_empty_string(
    scripted_anthropic, tool_manager, fake_store
):
    """Fix A: if the second Anthropic call returns content=[], we return ''
    instead of crashing with IndexError."""
    fake_store.queue_results(
        documents=["d"],
        metadata=[{"course_title": "C", "lesson_number": 1}],
    )
    scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}),
        empty_response(),
    ])
    gen = _make_generator()
    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )
    assert out == ""


def test_no_tool_empty_content_returns_empty_string(scripted_anthropic):
    """Fix A: no-tool path also guards against empty content."""
    scripted_anthropic([empty_response()])
    gen = _make_generator()
    assert gen.generate_response("hi") == ""


def test_history_prepended_to_system_prompt(scripted_anthropic):
    client = scripted_anthropic([text_response("hi")])
    gen = _make_generator()
    gen.generate_response("hello", conversation_history="User: prior\nAssistant: earlier")
    system = client.calls[0]["system"]
    assert "Previous conversation:" in system
    assert "User: prior" in system


def test_no_history_no_prior_conversation_section(scripted_anthropic):
    client = scripted_anthropic([text_response("hi")])
    gen = _make_generator()
    gen.generate_response("hello")
    assert "Previous conversation:" not in client.calls[0]["system"]


def test_disable_temperature_env_var(monkeypatch, scripted_anthropic):
    monkeypatch.setenv("ANTHROPIC_DISABLE_TEMPERATURE", "1")
    gen = _make_generator()
    assert "temperature" not in gen.base_params


def test_default_has_temperature(scripted_anthropic):
    gen = _make_generator()
    assert gen.base_params.get("temperature") == 0


def test_system_prompt_mentions_both_tools():
    """F3 regression: system prompt must describe both search_course_content and get_course_outline."""
    assert "search_course_content" in AIGenerator.SYSTEM_PROMPT
    assert "get_course_outline" in AIGenerator.SYSTEM_PROMPT
