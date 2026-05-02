import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from vector_store import SearchResults  # noqa: E402


class FakeVectorStore:
    """In-memory stand-in for VectorStore. Exposes only what CourseSearchTool
    and CourseOutlineTool actually call."""

    def __init__(self):
        self.next_search_result: Optional[SearchResults] = None
        self.search_raises: Optional[Exception] = None
        self.search_calls: List[Dict[str, Any]] = []

        self.course_links: Dict[str, Optional[str]] = {}
        self.lesson_links: Dict[tuple, Optional[str]] = {}
        self.catalog_rows: Dict[str, Dict[str, Any]] = {}

    def queue_results(self, documents, metadata, distances=None, error=None):
        distances = distances or [0.1] * len(documents)
        self.next_search_result = SearchResults(
            documents=list(documents),
            metadata=list(metadata),
            distances=list(distances),
            error=error,
        )

    def queue_error(self, error_msg: str):
        self.next_search_result = SearchResults.empty(error_msg)

    def queue_empty(self):
        self.next_search_result = SearchResults(documents=[], metadata=[], distances=[])

    def search(self, query, course_name=None, lesson_number=None, limit=None):
        self.search_calls.append(
            {"query": query, "course_name": course_name, "lesson_number": lesson_number, "limit": limit}
        )
        if self.search_raises:
            raise self.search_raises
        if self.next_search_result is None:
            return SearchResults(documents=[], metadata=[], distances=[])
        result = self.next_search_result
        self.next_search_result = None
        return result

    def get_course_link(self, course_title: str) -> Optional[str]:
        return self.course_links.get(course_title)

    def get_lesson_link(self, course_title: str, lesson_number: int) -> Optional[str]:
        return self.lesson_links.get((course_title, lesson_number))

    def seed_course(self, title, course_link, lessons):
        """lessons: list of {lesson_number, lesson_title, lesson_link}"""
        self.course_links[title] = course_link
        for lesson in lessons:
            self.lesson_links[(title, lesson["lesson_number"])] = lesson.get("lesson_link")
        import json
        self.catalog_rows[title] = {
            "title": title,
            "course_link": course_link,
            "lessons_json": json.dumps(lessons),
        }

    @property
    def course_catalog(self):
        fake = self

        class _Catalog:
            def get(self, ids=None):
                if ids is None:
                    return {"metadatas": list(fake.catalog_rows.values())}
                rows = [fake.catalog_rows[i] for i in ids if i in fake.catalog_rows]
                return {"metadatas": rows} if rows else {"metadatas": []}

            def query(self, query_texts, n_results=1):
                q = query_texts[0].lower()
                for title in fake.catalog_rows:
                    if q in title.lower():
                        return {
                            "documents": [[title]],
                            "metadatas": [[{"title": title}]],
                        }
                return {"documents": [[]], "metadatas": [[]]}

        return _Catalog()

    def _resolve_course_name(self, course_name: str) -> Optional[str]:
        needle = course_name.lower()
        for title in self.catalog_rows:
            if needle in title.lower():
                return title
        return None


# ---------- Anthropic response builders ----------

def _block(**kw):
    return SimpleNamespace(**kw)


def text_response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[_block(type="text", text=text)],
    )


def tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "toolu_01"):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            _block(
                type="tool_use",
                name=tool_name,
                input=tool_input,
                id=tool_id,
            )
        ],
    )


def empty_response():
    return SimpleNamespace(stop_reason="end_turn", content=[])


class ScriptedAnthropic:
    """A drop-in replacement for the object returned by anthropic.Anthropic(...).
    The caller queues up responses; each call to messages.create pops one."""

    def __init__(self, responses: List[Any]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []
        self.messages = self  # mimic client.messages.create

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("ScriptedAnthropic ran out of queued responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fake_store():
    return FakeVectorStore()


@pytest.fixture
def scripted_anthropic(monkeypatch):
    """Factory — returns a function the test calls with a list of responses."""
    def _install(responses):
        import anthropic
        client = ScriptedAnthropic(responses)
        monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
        return client
    return _install


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure ANTHROPIC_DISABLE_TEMPERATURE is deterministic per test.
    Tests that care about this explicitly set it."""
    monkeypatch.delenv("ANTHROPIC_DISABLE_TEMPERATURE", raising=False)
