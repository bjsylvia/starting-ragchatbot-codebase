"""Exercises CourseSearchTool.execute() against a FakeVectorStore."""
import pytest

from search_tools import CourseSearchTool


@pytest.fixture
def tool(fake_store):
    return CourseSearchTool(fake_store)


def test_happy_path_no_filters(tool, fake_store):
    fake_store.queue_results(
        documents=["Reranking uses cross-encoders.", "Query expansion helps recall."],
        metadata=[
            {"course_title": "Advanced Retrieval for AI with Chroma", "lesson_number": 4},
            {"course_title": "Advanced Retrieval for AI with Chroma", "lesson_number": 3},
        ],
    )
    fake_store.lesson_links[("Advanced Retrieval for AI with Chroma", 4)] = "https://example.com/l4"
    fake_store.lesson_links[("Advanced Retrieval for AI with Chroma", 3)] = "https://example.com/l3"

    out = tool.execute(query="reranking")

    assert "Advanced Retrieval for AI with Chroma - Lesson 4" in out
    assert "Reranking uses cross-encoders." in out
    assert fake_store.search_calls == [
        {"query": "reranking", "course_name": None, "lesson_number": None, "limit": None}
    ]
    assert len(tool.last_sources) == 2
    assert tool.last_sources[0] == {
        "text": "Advanced Retrieval for AI with Chroma - Lesson 4",
        "link": "https://example.com/l4",
    }


def test_course_name_filter_is_forwarded(tool, fake_store):
    fake_store.queue_results(
        documents=["doc"],
        metadata=[{"course_title": "MCP: Build Rich-Context AI Apps with Anthropic", "lesson_number": 1}],
    )
    tool.execute(query="intro", course_name="MCP")
    assert fake_store.search_calls[-1]["course_name"] == "MCP"


def test_lesson_number_filter_is_forwarded(tool, fake_store):
    fake_store.queue_results(
        documents=["doc"],
        metadata=[{"course_title": "X", "lesson_number": 2}],
    )
    tool.execute(query="anything", lesson_number=2)
    assert fake_store.search_calls[-1]["lesson_number"] == 2


def test_both_filters_forwarded(tool, fake_store):
    fake_store.queue_results(
        documents=["doc"],
        metadata=[{"course_title": "X", "lesson_number": 2}],
    )
    tool.execute(query="q", course_name="X", lesson_number=2)
    assert fake_store.search_calls[-1] == {
        "query": "q", "course_name": "X", "lesson_number": 2, "limit": None
    }


def test_empty_results_message_with_course_filter(tool, fake_store):
    fake_store.queue_empty()
    out = tool.execute(query="q", course_name="Nonexistent")
    assert "No relevant content found" in out
    assert "Nonexistent" in out
    assert tool.last_sources == []


def test_empty_results_message_with_lesson_filter(tool, fake_store):
    fake_store.queue_empty()
    out = tool.execute(query="q", lesson_number=99)
    assert "lesson 99" in out
    assert tool.last_sources == []


def test_empty_results_with_both_filters(tool, fake_store):
    fake_store.queue_empty()
    out = tool.execute(query="q", course_name="X", lesson_number=2)
    assert "X" in out and "lesson 2" in out


def test_error_from_store_is_returned_as_string(tool, fake_store):
    fake_store.queue_error("Search error: boom")
    out = tool.execute(query="q")
    assert out == "Search error: boom"
    assert tool.last_sources == []


def test_sources_are_dicts_with_text_and_link(tool, fake_store):
    """F1 regression guard: sources must be {text, link} dicts, never bare strings."""
    fake_store.queue_results(
        documents=["d"],
        metadata=[{"course_title": "C", "lesson_number": 1}],
    )
    fake_store.lesson_links[("C", 1)] = "https://example.com/1"
    tool.execute(query="q")
    assert tool.last_sources[0] == {"text": "C - Lesson 1", "link": "https://example.com/1"}
    assert isinstance(tool.last_sources[0], dict)


def test_course_level_source_uses_get_course_link(tool, fake_store):
    """When lesson_number is absent in metadata, source should use get_course_link."""
    fake_store.queue_results(
        documents=["overview"],
        metadata=[{"course_title": "C", "lesson_number": None}],
    )
    fake_store.course_links["C"] = "https://example.com/course"
    tool.execute(query="q")
    assert tool.last_sources[0] == {"text": "C", "link": "https://example.com/course"}


def test_missing_lesson_link_yields_none_but_valid_dict(tool, fake_store):
    fake_store.queue_results(
        documents=["d"],
        metadata=[{"course_title": "C", "lesson_number": 42}],
    )
    # no lesson_links entry for (C, 42)
    tool.execute(query="q")
    assert tool.last_sources[0] == {"text": "C - Lesson 42", "link": None}


def test_last_sources_overwritten_between_calls(tool, fake_store):
    fake_store.queue_results(
        documents=["a"],
        metadata=[{"course_title": "C1", "lesson_number": 1}],
    )
    tool.execute(query="q1")
    first = tool.last_sources

    fake_store.queue_results(
        documents=["b"],
        metadata=[{"course_title": "C2", "lesson_number": 2}],
    )
    tool.execute(query="q2")
    assert tool.last_sources != first
    assert tool.last_sources[0]["text"] == "C2 - Lesson 2"


def test_tool_definition_shape(tool):
    defn = tool.get_tool_definition()
    assert defn["name"] == "search_course_content"
    assert "query" in defn["input_schema"]["properties"]
    assert defn["input_schema"]["required"] == ["query"]
