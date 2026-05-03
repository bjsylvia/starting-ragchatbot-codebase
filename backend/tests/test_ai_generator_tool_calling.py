"""Exercises AIGenerator.generate_response() with a mocked Anthropic client.

Tool-calling path = two-hop: first Claude call may return stop_reason='tool_use',
then the generator runs the tool and makes a second call without tools to get
the final text.
"""
import pytest

from ai_generator import AIGenerator
from search_tools import CourseOutlineTool, CourseSearchTool, ToolManager
from tests.conftest import text_response, tool_use_response, empty_response


@pytest.fixture
def tool_manager(fake_store):
    mgr = ToolManager()
    mgr.register_tool(CourseSearchTool(fake_store))
    mgr.register_tool(CourseOutlineTool(fake_store))
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


def test_tool_use_path_one_round_then_text(scripted_anthropic, tool_manager, fake_store):
    """Round 1 returns tool_use; round 2's API call carries tools (Claude may
    want to invoke another one) but Claude returns text and we return.

    Contract change vs the original one-shot design: the follow-up call now
    keeps `tools` attached because sequential tool-calling lets Claude issue
    a second tool_use. Tools only get stripped on the LAST allowed round."""
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
    # Follow-up call still has tools attached — Claude chose text on its own.
    assert "tools" in client.calls[1]
    # Follow-up call's messages carry the tool_use + tool_result pair
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


# ---------------------------------------------------------------------------
# Sequential tool-calling (up to MAX_TOOL_ROUNDS rounds)
# ---------------------------------------------------------------------------


def test_two_sequential_tool_rounds_happy_path(scripted_anthropic, tool_manager, fake_store):
    """Round 1: get_course_outline. Round 2: search_course_content using the
    lesson title discovered in round 1. Final call (no tools) returns text."""
    # Seed outline-tool data
    fake_store.seed_course(
        "Course X",
        "https://example.com/x",
        lessons=[
            {"lesson_number": 4, "lesson_title": "Cross-encoder re-ranking", "lesson_link": None},
        ],
    )
    # Seed search result for round 2
    fake_store.queue_results(
        documents=["Other course also teaches cross-encoders."],
        metadata=[{"course_title": "Advanced Retrieval", "lesson_number": 7}],
    )

    client = scripted_anthropic([
        tool_use_response("get_course_outline", {"course_name": "Course X"}, tool_id="r1"),
        tool_use_response("search_course_content", {"query": "Cross-encoder re-ranking"}, tool_id="r2"),
        text_response("Advanced Retrieval lesson 7 covers the same topic."),
    ])
    gen = _make_generator()

    out = gen.generate_response(
        "Find a course that discusses the same topic as lesson 4 of Course X.",
        tools=tool_manager.get_tool_definitions(),
        tool_manager=tool_manager,
    )

    assert out == "Advanced Retrieval lesson 7 covers the same topic."
    assert len(client.calls) == 3
    # Round 1 and round 2 API calls carry tools; the final call doesn't.
    assert "tools" in client.calls[0]
    assert "tools" in client.calls[1]
    assert "tools" not in client.calls[2]
    # The final call's messages preserve both rounds' tool_use + tool_result.
    messages = client.calls[2]["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    # Tool results match each round's tool_use_id.
    r1_result = messages[2]["content"][0]
    r2_result = messages[4]["content"][0]
    assert r1_result["tool_use_id"] == "r1"
    assert r2_result["tool_use_id"] == "r2"


def test_round2_tool_use_forces_final_call_without_tools(scripted_anthropic, tool_manager, fake_store):
    """If Claude keeps asking for tools past the round cap, the last call
    strips tools so Claude must produce text."""
    fake_store.seed_course("A", "https://a", lessons=[])
    fake_store.queue_results(documents=["doc"], metadata=[{"course_title": "A", "lesson_number": 1}])

    # Queue 2 tool_use responses then a text. Claude would call tools forever
    # given the chance; the code strips tools on the last round.
    client = scripted_anthropic([
        tool_use_response("get_course_outline", {"course_name": "A"}, tool_id="r1"),
        tool_use_response("search_course_content", {"query": "q"}, tool_id="r2"),
        text_response("I have enough."),
    ])
    gen = _make_generator()

    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )

    assert out == "I have enough."
    assert len(client.calls) == 3
    assert "tools" not in client.calls[2], "final call must strip tools"


def test_round_cap_prevents_third_tool_execution(scripted_anthropic, tool_manager, fake_store):
    """Regardless of what Claude returns on the tools-stripped call, the tool
    manager executes exactly MAX_TOOL_ROUNDS times."""
    fake_store.seed_course("A", "https://a", lessons=[])
    fake_store.queue_results(documents=["doc"], metadata=[{"course_title": "A", "lesson_number": 1}])

    scripted_anthropic([
        tool_use_response("get_course_outline", {"course_name": "A"}, tool_id="r1"),
        tool_use_response("search_course_content", {"query": "q"}, tool_id="r2"),
        text_response("done"),
    ])
    gen = _make_generator()
    gen.generate_response("q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager)

    # FakeVectorStore's search_calls counts one per search_course_content; the
    # outline tool doesn't hit .search. Combined, exactly 2 tool executions.
    assert len(fake_store.search_calls) == 1
    # Outline tool was called once (we seeded the course so it succeeded).
    assert "A" in fake_store.catalog_rows


def test_round2_tool_error_reaches_claude_and_recovers(scripted_anthropic, tool_manager, fake_store):
    """A tool exception in round 2 becomes a 'Tool error: ...' tool_result so
    Claude can still produce a reasonable final answer."""
    # Round 1 succeeds (outline). Round 2's search raises.
    fake_store.seed_course("A", "https://a", lessons=[])
    fake_store.search_raises = RuntimeError("chromadb exploded")

    client = scripted_anthropic([
        tool_use_response("get_course_outline", {"course_name": "A"}, tool_id="r1"),
        tool_use_response("search_course_content", {"query": "q"}, tool_id="r2"),
        text_response("Couldn't finish the search, but here's what I know."),
    ])
    gen = _make_generator()

    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )

    assert out == "Couldn't finish the search, but here's what I know."
    # The final call's last user-turn carries the tool_error string
    final_messages = client.calls[2]["messages"]
    r2_result = final_messages[4]["content"][0]
    assert r2_result["tool_use_id"] == "r2"
    assert "Tool error" in r2_result["content"]
    assert "chromadb exploded" in r2_result["content"]


def test_sequential_tool_inputs_reflect_prior_results(scripted_anthropic, tool_manager, fake_store):
    """Round 2 actually gets called with inputs Claude chose after seeing
    round 1 — verified by the distinct search query emitted by the script."""
    fake_store.seed_course(
        "Course X",
        "https://example.com/x",
        lessons=[{"lesson_number": 4, "lesson_title": "Reranking", "lesson_link": None}],
    )
    fake_store.queue_results(
        documents=["hit"], metadata=[{"course_title": "Other", "lesson_number": 2}]
    )

    scripted_anthropic([
        tool_use_response("get_course_outline", {"course_name": "Course X"}, tool_id="r1"),
        tool_use_response("search_course_content", {"query": "Reranking"}, tool_id="r2"),
        text_response("ok"),
    ])
    gen = _make_generator()
    gen.generate_response("q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager)

    assert len(fake_store.search_calls) == 1
    assert fake_store.search_calls[0]["query"] == "Reranking"


def test_system_prompt_describes_two_rounds():
    """System prompt advertises sequential tool calling (required by spec)."""
    prompt = AIGenerator.SYSTEM_PROMPT
    assert "One tool call per query maximum" not in prompt
    assert "two" in prompt.lower()
    assert "sequential" in prompt.lower()


def test_max_tool_rounds_is_two():
    """Contract: the cap is 2 rounds."""
    assert AIGenerator.MAX_TOOL_ROUNDS == 2


def test_round1_tool_error_does_not_break_second_round(scripted_anthropic, tool_manager, fake_store):
    """If the round-1 tool raises, Claude still gets a 'Tool error' result and
    can legitimately call a different tool in round 2."""
    fake_store.search_raises = RuntimeError("oops")
    # After round 1 fails, Claude tries the outline tool instead.
    fake_store.seed_course("A", "https://a", lessons=[])

    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}, tool_id="r1"),
        tool_use_response("get_course_outline", {"course_name": "A"}, tool_id="r2"),
        text_response("recovered via outline"),
    ])
    gen = _make_generator()

    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )

    assert out == "recovered via outline"
    # Round-1 tool_result contained the error. The final call's messages list
    # is the accumulated history; index 2 is the round-1 user(tool_result).
    final_messages = client.calls[-1]["messages"]
    r1_result = final_messages[2]["content"][0]
    assert r1_result["tool_use_id"] == "r1"
    assert "Tool error" in r1_result["content"]
    assert "oops" in r1_result["content"]


def test_claude_stops_at_round_one_with_no_tool_use(scripted_anthropic, tool_manager, fake_store):
    """Early-termination regression: if Claude returns text on round 2's call,
    we return without making a third call even though one more round is allowed."""
    fake_store.queue_results(
        documents=["d"], metadata=[{"course_title": "C", "lesson_number": 1}]
    )
    client = scripted_anthropic([
        tool_use_response("search_course_content", {"query": "q"}, tool_id="r1"),
        text_response("early exit"),
    ])
    gen = _make_generator()
    out = gen.generate_response(
        "q", tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager
    )
    assert out == "early exit"
    assert len(client.calls) == 2
