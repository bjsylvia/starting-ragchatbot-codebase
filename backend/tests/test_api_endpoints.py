"""API-layer tests for the FastAPI endpoints.

These tests exercise request parsing, response shape, error mapping, and
session plumbing without touching Anthropic, ChromaDB, or the frontend
static mount. The RAG system is a stub (see conftest.StubRAGSystem); the
app itself is rebuilt inline (see conftest._build_test_app) to sidestep
the ../frontend StaticFiles mount in backend/app.py.
"""
import pytest


pytestmark = pytest.mark.api


class TestQueryEndpoint:
    def test_query_with_explicit_session_id_returns_answer_and_sources(
        self, api_client, stub_rag
    ):
        stub_rag.next_answer = "Reranking uses a cross-encoder."
        stub_rag.next_sources = [
            {"text": "Advanced Retrieval - Lesson 4", "link": "https://example.com/l4"}
        ]

        resp = api_client.post(
            "/api/query",
            json={"query": "What is reranking?", "session_id": "sess-abc"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "Reranking uses a cross-encoder."
        assert body["session_id"] == "sess-abc"
        assert body["sources"] == [
            {"text": "Advanced Retrieval - Lesson 4", "link": "https://example.com/l4"}
        ]

        assert stub_rag.query_calls == [
            {"query": "What is reranking?", "session_id": "sess-abc"}
        ]

    def test_query_without_session_id_allocates_one(self, api_client, stub_rag):
        resp = api_client.post("/api/query", json={"query": "hi"})

        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        assert sid.startswith("test-session-")
        # The allocated session is what got passed to rag.query.
        assert stub_rag.query_calls[0]["session_id"] == sid

    def test_query_with_empty_string_is_still_forwarded(self, api_client, stub_rag):
        """Empty query is syntactically valid — the server shouldn't 422 it.
        Whether to allow it is a product decision; current behavior forwards."""
        resp = api_client.post("/api/query", json={"query": ""})
        assert resp.status_code == 200
        assert stub_rag.query_calls[0]["query"] == ""

    def test_query_with_no_sources_returns_empty_list(self, api_client, stub_rag):
        stub_rag.next_answer = "2 + 2 = 4."
        stub_rag.next_sources = []

        resp = api_client.post("/api/query", json={"query": "What is 2+2?"})

        assert resp.status_code == 200
        assert resp.json()["sources"] == []

    def test_query_missing_body_returns_422(self, api_client):
        resp = api_client.post("/api/query", json={})
        assert resp.status_code == 422

    def test_query_wrong_type_returns_422(self, api_client):
        resp = api_client.post("/api/query", json={"query": 123})
        assert resp.status_code == 422

    def test_query_rag_exception_maps_to_500(self, api_client, stub_rag):
        stub_rag.query_raises = RuntimeError("something broke")

        resp = api_client.post("/api/query", json={"query": "anything"})

        assert resp.status_code == 500
        assert "something broke" in resp.json()["detail"]

    def test_query_response_source_link_can_be_null(self, api_client, stub_rag):
        stub_rag.next_sources = [{"text": "Course X", "link": None}]
        resp = api_client.post("/api/query", json={"query": "x"})
        assert resp.status_code == 200
        assert resp.json()["sources"] == [{"text": "Course X", "link": None}]


class TestCoursesEndpoint:
    def test_courses_returns_analytics(self, api_client, stub_rag):
        stub_rag.analytics = {
            "total_courses": 3,
            "course_titles": ["Course A", "Course B", "Course C"],
        }

        resp = api_client.get("/api/courses")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_courses"] == 3
        assert body["course_titles"] == ["Course A", "Course B", "Course C"]

    def test_courses_empty_catalog(self, api_client, stub_rag):
        resp = api_client.get("/api/courses")
        assert resp.status_code == 200
        assert resp.json() == {"total_courses": 0, "course_titles": []}

    def test_courses_exception_maps_to_500(self, api_client, stub_rag):
        stub_rag.analytics_raises = RuntimeError("chroma down")
        resp = api_client.get("/api/courses")
        assert resp.status_code == 500
        assert "chroma down" in resp.json()["detail"]


class TestSessionEndpoint:
    def test_delete_existing_session_returns_204(self, api_client, stub_rag):
        stub_rag.session_manager.sessions["sess-1"] = ["msg1", "msg2"]

        resp = api_client.delete("/api/session/sess-1")

        assert resp.status_code == 204
        assert "sess-1" not in stub_rag.session_manager.sessions

    def test_delete_unknown_session_is_idempotent(self, api_client, stub_rag):
        resp = api_client.delete("/api/session/never-existed")
        assert resp.status_code == 204


class TestRoot:
    def test_root_returns_ok(self, api_client):
        resp = api_client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCORS:
    def test_cors_headers_present_on_query(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={"query": "hi"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"
