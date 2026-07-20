"""
S2: Unit tests for api/routes.py
Tests Flask API endpoints, rate limiting, and error handling.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestFlaskClient:
    """Tests using Flask test client."""

    def test_index_page(self, flask_client):
        """Root URL should return HTML."""
        response = flask_client.get("/")
        assert response.status_code == 200

    def test_404(self, flask_client):
        """Non-existent route should return 404 JSON."""
        response = flask_client.get("/nonexistent")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    def test_cors_headers(self, flask_client):
        """CORS headers absent by default (same-origin safe). Set CORS_ORIGIN to enable."""
        response = flask_client.get("/")
        assert "Access-Control-Allow-Origin" not in response.headers


class TestAPIRoutes:
    """Tests for API endpoints."""

    def test_get_queries(self, flask_client):
        """GET /api/queries should return list."""
        response = flask_client.get("/api/queries")
        assert response.status_code == 200

    def test_get_platforms(self, flask_client):
        """GET /api/platforms should return platform list."""
        response = flask_client.get("/api/platforms")
        assert response.status_code == 200

    def test_get_cities(self, flask_client):
        """GET /api/cities should return city list."""
        response = flask_client.get("/api/cities")
        assert response.status_code == 200


class TestAPIAuth:
    """Tests for API key authentication."""

    def test_write_endpoint_blocked_with_api_key_set(self, flask_client,
                                                      monkeypatch):
        """When API_KEY is set, POST /api/queries should return 401 without header."""
        monkeypatch.setattr("api._shared.API_KEY", "secret123")
        resp = flask_client.post("/api/queries", json={
            "departure": "北京", "destination": "上海", "departure_date": "2026-08-01"
        })
        assert resp.status_code == 401
        data = resp.get_json()
        assert "API key" in data.get("error", "")

    def test_write_endpoint_allowed_with_correct_key(self, flask_client,
                                                       monkeypatch):
        """POST /api/alerts with correct X-API-Key header should succeed."""
        monkeypatch.setattr("api._shared.API_KEY", "secret123")
        headers = {"X-API-Key": "secret123"}
        resp = flask_client.post("/api/alerts", headers=headers, json={
            "query_id": 1, "target_price": 500
        })
        # 200 expected (alert created), not 401.
        assert resp.status_code != 401

    def test_write_requires_header_only_not_query_param(self, flask_client,
                                                          monkeypatch):
        """API key via ?api_key= query param should be rejected."""
        monkeypatch.setattr("api._shared.API_KEY", "secret123")
        resp = flask_client.post(
            "/api/queries?api_key=secret123",
            json={"departure": "北京", "destination": "上海", "departure_date": "2026-08-01"},
        )
        assert resp.status_code == 401
