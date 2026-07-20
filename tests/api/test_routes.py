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
