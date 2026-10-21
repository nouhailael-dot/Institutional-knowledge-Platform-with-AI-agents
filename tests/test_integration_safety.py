"""Offline regression checks for the Phase 12 merge."""
from unittest.mock import MagicMock, patch

import pytest

from src import embed


def test_empty_assembly_never_opens_index_writer():
    with patch.object(embed, "assemble_all", return_value=[]), \
            patch.object(embed, "embed_texts") as embeddings, \
            patch.object(embed, "get_connection") as connect:
        with pytest.raises(RuntimeError, match="left unchanged"):
            embed.build_index()
    embeddings.assert_not_called()
    connect.assert_not_called()


@pytest.mark.parametrize("vectors", [[], [[]], [[1.0], [2.0]]])
def test_incomplete_embeddings_never_open_index_writer(vectors):
    docs = [{"entity_id": "00000000-0000-0000-0000-000000000001",
             "entity_type": "actor", "name": "Live actor", "doc_text": "Evidence"}]
    with patch.object(embed, "assemble_all", return_value=docs), \
            patch.object(embed, "embed_texts", return_value=vectors), \
            patch.object(embed, "get_connection") as connect:
        with pytest.raises(RuntimeError, match="Incomplete embeddings"):
            embed.build_index()
    connect.assert_not_called()


def test_index_prunes_stale_documents_after_complete_replacement():
    docs = [{"entity_id": "00000000-0000-0000-0000-000000000001",
             "entity_type": "actor", "name": "Live actor", "doc_text": "Evidence"}]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch.object(embed, "assemble_all", return_value=docs), \
            patch.object(embed, "embed_texts", return_value=[[0.1]]), \
            patch.object(embed, "get_connection", return_value=connection):
        assert embed.build_index() == 1
    statements = cursor.execute.call_args_list
    assert "INSERT INTO search_doc" in statements[0].args[0]
    assert "DELETE FROM search_doc" in statements[1].args[0]
    assert statements[1].args[1] == ([docs[0]["entity_id"]],)
    connection.commit.assert_called_once()


def test_fastapi_starts_with_unique_routes_and_both_review_workflows():
    from fastapi.testclient import TestClient
    from backend.app import app

    routes = [(method, route.path) for route in app.routes
              for method in getattr(route, "methods", [])]
    assert len(routes) == len(set(routes))
    for path in ("/api/review/category-decisions",
                 "/api/review/candidates/{candidate_id}/review-item-decision",
                 "/api/review/candidates/{candidate_id}/decision",
                 "/api/discovery/requests", "/api/discovery/actors/{actor_id}/plan"):
        assert ("POST", path) in routes
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
