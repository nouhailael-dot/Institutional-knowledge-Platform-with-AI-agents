from __future__ import annotations

import json
import socket
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from agents.reporting.artifacts import ArtifactBuilder, MissingCitations
from agents.reporting.db import MissingReadOnlyDatabaseUrl, readonly_database_url
from agents.reporting.logging import InMemoryToolLogger
from agents.reporting.loop import LLMTurn, ToolCall, run_reporting_agent
from agents.reporting.tools import ToolSpec, ReportingTools

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StubLLM:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0

    def next_turn(self, **kwargs):
        self.calls += 1
        assert kwargs["tools"]
        if self.turns:
            return self.turns.pop(0)
        return LLMTurn(text="done")


class StubTools:
    def __init__(self):
        self.calls = []

    def registry(self):
        return {
            "query_actors": ToolSpec(
                "query_actors",
                "query actors",
                {"type": "object", "properties": {}, "additionalProperties": False},
                lambda **kwargs: [{"entity_id": str(uuid.uuid4()), "name": "Actor A"}],
            )
        }

    def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return self.registry()[tool_name].handler(**arguments)


class FailingTools:
    def registry(self):
        return {
            "query_actors": ToolSpec(
                "query_actors",
                "query actors",
                {"type": "object", "properties": {}, "additionalProperties": False},
                self.query_actors,
            )
        }

    def call(self, tool_name, arguments):
        return self.registry()[tool_name].handler(**arguments)

    def query_actors(self, **kwargs):
        raise RuntimeError(
            "could not connect to postgresql://user:secret@db.example/ghus?sslmode=require password=abc123456"
        )


class InspectingLLM:
    def __init__(self):
        self.calls = 0
        self.model_payload = ""

    def next_turn(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMTurn(
                tool_calls=[ToolCall("tool-1", "query_actors", {"limit": 1})],
                raw_assistant_content=[
                    {"type": "tool_use", "id": "tool-1", "name": "query_actors", "input": {"limit": 1}}
                ],
            )
        self.model_payload = json.dumps(kwargs["messages"], sort_keys=True, default=str)
        return LLMTurn(text="The tool failed safely.")


class FakeRows:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self):
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params or {})
        return FakeRows()

    def commit(self):
        pass

    def rollback(self):
        pass


def test_reporting_loop_uses_expected_tool_for_question():
    tool_call = ToolCall("tool-1", "query_actors", {"sector": "ENERGY", "limit": 5})
    llm = StubLLM(
        [
            LLMTurn(
                tool_calls=[tool_call],
                raw_assistant_content=[
                    {"type": "tool_use", "id": "tool-1", "name": "query_actors", "input": tool_call.arguments}
                ],
            ),
            LLMTurn(text="There are relevant energy actors."),
        ]
    )
    tools = StubTools()
    tool_logger = InMemoryToolLogger()

    result = run_reporting_agent(
        "Which actors are relevant to energy?",
        session=object(),
        llm=llm,
        tools=tools,
        tool_logger=tool_logger,
    )

    assert result.status == "succeeded"
    assert tools.calls == [("query_actors", {"sector": "ENERGY", "limit": 5})]
    assert [entry.phase for entry in tool_logger.entries] == ["call", "result"]
    assert all(entry.request_id == result.request_id for entry in tool_logger.entries)


def test_iteration_cap_hard_stops():
    llm = StubLLM(
        [
            LLMTurn(
                tool_calls=[ToolCall("tool-1", "query_actors", {"limit": 1})],
                raw_assistant_content=[
                    {"type": "tool_use", "id": "tool-1", "name": "query_actors", "input": {"limit": 1}}
                ],
            )
        ]
    )
    result = run_reporting_agent(
        "Keep looking forever",
        session=object(),
        llm=llm,
        tools=StubTools(),
        tool_logger=InMemoryToolLogger(),
        max_iterations=1,
    )

    assert result.status == "iteration_cap_exceeded"
    assert "max_iterations=1" in result.answer


def test_budget_cap_hard_stops():
    llm = StubLLM([LLMTurn(text="expensive answer", cost_usd=1.25)])
    result = run_reporting_agent(
        "Summarize everything",
        session=object(),
        llm=llm,
        tools=StubTools(),
        tool_logger=InMemoryToolLogger(),
        usd_budget=0.10,
    )

    assert result.status == "budget_exceeded"
    assert "exceeded" in result.answer


def test_draft_email_returns_draft_without_network(monkeypatch):
    opened_network = False

    def fail_network(*args, **kwargs):
        nonlocal opened_network
        opened_network = True
        raise AssertionError("draft_email must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    tools = ReportingTools(FakeSession())
    draft = tools.draft_email(
        to=["person@example.org"],
        subject="GHUS brief",
        body="Draft body only.",
    )

    assert draft["status"] == "draft"
    assert draft["to"] == ["person@example.org"]
    assert opened_network is False


def test_missing_readonly_connection_string_raises_without_owner_fallback():
    with pytest.raises(MissingReadOnlyDatabaseUrl):
        readonly_database_url(env={"DATABASE_URL": "postgresql://owner-connection"})


def test_reporting_agent_uses_separate_query_log_session(monkeypatch):
    read_session = FakeSession()
    log_session = FakeSession()

    @contextmanager
    def fake_readonly_session():
        yield read_session

    @contextmanager
    def fake_query_log_session():
        yield log_session

    monkeypatch.setattr("agents.reporting.loop.readonly_session", fake_readonly_session)
    monkeypatch.setattr("agents.reporting.loop.query_log_session", fake_query_log_session)

    result = run_reporting_agent(
        "Which actors are relevant to energy?",
        llm=StubLLM(
            [
                LLMTurn(
                    tool_calls=[ToolCall("tool-1", "query_actors", {"limit": 1})],
                    raw_assistant_content=[
                        {"type": "tool_use", "id": "tool-1", "name": "query_actors", "input": {"limit": 1}}
                    ],
                ),
                LLMTurn(text="done"),
            ]
        ),
        tools=StubTools(),
    )

    assert result.status == "succeeded"
    assert not read_session.statements
    assert any("INSERT INTO query_log" in sql for sql in log_session.statements)


def test_tool_exception_is_sanitized_for_logs_and_model():
    llm = InspectingLLM()
    tool_logger = InMemoryToolLogger()

    result = run_reporting_agent(
        "Find actors",
        session=object(),
        llm=llm,
        tools=FailingTools(),
        tool_logger=tool_logger,
    )

    assert result.status == "succeeded"
    logged_payload = json.dumps([entry.payload for entry in tool_logger.entries], sort_keys=True, default=str)
    assert "user:secret" not in logged_payload
    assert "db.example" not in logged_payload
    assert "abc123456" not in logged_payload
    assert "RuntimeError" in logged_payload
    assert "<redacted" in logged_payload
    assert "user:secret" not in llm.model_payload
    assert "db.example" not in llm.model_payload
    assert "abc123456" not in llm.model_payload
    assert "See query_log" in llm.model_payload


def test_query_actors_uses_limit_cap_and_bound_params():
    session = FakeSession()
    tools = ReportingTools(session)
    tools.query_actors(sector="ENERGY", country="USA", actor_type="startup", limit=999)

    assert session.params[-1]["limit"] == 100
    assert session.params[-1]["sector"] == "ENERGY"
    assert ":sector" in session.statements[-1]
    assert "ENERGY" not in session.statements[-1]


def test_artifact_builder_requires_entity_citations(tmp_path):
    builder = ArtifactBuilder(
        template_dir=PROJECT_ROOT / "agents" / "reporting" / "templates",
        output_dir=tmp_path,
    )
    with pytest.raises(MissingCitations):
        builder.build_pdf({"title": "No citations", "body": "A claim without entity ids."})


def test_xlsx_artifact_includes_cited_entity_ids(tmp_path):
    entity_id = str(uuid.uuid4())
    builder = ArtifactBuilder(
        template_dir=PROJECT_ROOT / "agents" / "reporting" / "templates",
        output_dir=tmp_path,
    )
    result = builder.build_xlsx(
        {
            "title": "Cited report",
            "body": ["One cited figure."],
            "citations": [entity_id],
        }
    )

    assert result.artifact_type == "xlsx"
    assert result.entity_ids == [entity_id]
    assert Path(result.path).exists()


def test_each_artifact_figure_requires_entity_ids(tmp_path):
    builder = ArtifactBuilder(
        template_dir=PROJECT_ROOT / "agents" / "reporting" / "templates",
        output_dir=tmp_path,
    )
    with pytest.raises(MissingCitations, match=r"figures\[0\]"):
        builder.build_pdf(
            {
                "title": "Uncited figure",
                "body": "A figure needs a source entity.",
                "figures": [{"title": "Actors by sector", "value": 12}],
            }
        )
