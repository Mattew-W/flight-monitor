"""
S2: Unit tests for core/price_prediction.py
Tests pure forecast functions and route classification.
"""

import math
import pytest
from core.price_prediction import (
    _stable_seed,
    _linear_regression,
    _compute_residual_std,
    _wma_forecast,
    _ci_bands,
    HolidayManager,
    COMPETITIVE_ROUTES,
    MONOPOLY_ROUTES,
    BUDGET_ROUTES,
)


class TestStableSeed:
    """Tests for _stable_seed deterministic seed function."""

    def test_same_input_same_seed(self):
        s1 = _stable_seed("北京", "上海", "2026-08-01")
        s2 = _stable_seed("北京", "上海", "2026-08-01")
        assert s1 == s2

    def test_different_input_different_seed(self):
        s1 = _stable_seed("北京", "上海")
        s2 = _stable_seed("上海", "北京")
        assert s1 != s2

    def test_integer_parts(self):
        s = _stable_seed("CA1501", 850, "2026-08-01")
        assert isinstance(s, int)
        assert s > 0

    def test_empty_parts(self):
        s = _stable_seed()
        assert isinstance(s, int)


class TestLinearRegression:
    """Tests for _linear_regression."""

    def test_perfect_line(self):
        xs = [1, 2, 3, 4, 5]
        ys = [2, 4, 6, 8, 10]  # y = 2x
        slope, intercept = _linear_regression(xs, ys)
        assert abs(slope - 2.0) < 0.01
        assert abs(intercept) < 0.01

    def test_single_point(self):
        slope, intercept = _linear_regression([1], [5])
        assert slope == 0.0
        assert intercept == 5.0

    def test_empty_lists(self):
        slope, intercept = _linear_regression([], [])
        assert slope == 0.0
        assert intercept == 0.0

    def test_flat_line(self):
        xs = [1, 2, 3]
        ys = [5, 5, 5]
        slope, intercept = _linear_regression(xs, ys)
        assert abs(slope) < 0.01
        assert abs(intercept - 5.0) < 0.01


class TestComputeResidualStd:
    """Tests for _compute_residual_std."""

    def test_perfect_fit(self):
        result = _compute_residual_std([2, 4, 6], 2.0, 0.0)
        assert result >= 1.0  # min clamp

    def test_small_sample(self):
        result = _compute_residual_std([100, 110], 10.0, 100.0)
        assert result > 0

    def test_normal_case(self):
        result = _compute_residual_std([100, 105, 95, 110, 98], 2.0, 98.0)
        assert result > 0


class TestWmaForecast:
    """Tests for _wma_forecast."""

    def test_basic_forecast(self):
        prices = [800, 820, 810, 830, 850]
        forecast, strength = _wma_forecast(prices, 7)
        assert len(forecast) == 7
        assert all(isinstance(v, (int, float)) for v in forecast)

    def test_single_price(self):
        forecast, strength = _wma_forecast([500], 5)
        assert len(forecast) == 5
        assert all(v == 500 for v in forecast)

    def test_empty_prices(self):
        forecast, strength = _wma_forecast([], 3)
        assert len(forecast) == 3
        assert all(v == 0 for v in forecast)

    def test_trend_strength(self):
        prices = [100, 110, 120, 130, 140]  # clear uptrend
        _, strength = _wma_forecast(prices, 5)
        assert 0 <= strength <= 1.0


class TestCiBands:
    """Tests for _ci_bands confidence interval."""

    def test_bands_width_increases(self):
        forecast = [800, 810, 820, 830, 840]
        lower, upper = _ci_bands(forecast, 50.0, 800, 5)
        assert len(lower) == 5
        assert len(upper) == 5
        # Upper band should be wider for later days
        assert (upper[-1] - lower[-1]) >= (upper[0] - lower[0])

    def test_lower_below_forecast(self):
        forecast = [800, 800, 800]
        lower, upper = _ci_bands(forecast, 30.0, 800, 3)
        assert all(l <= f for l, f in zip(lower, forecast))

    def test_upper_above_forecast(self):
        forecast = [800, 800, 800]
        lower, upper = _ci_bands(forecast, 30.0, 800, 3)
        assert all(u >= f for u, f in zip(upper, forecast))


class TestRouteClassification:
    """Tests for route classification sets."""

    def test_competitive_routes(self):
        assert ("北京", "上海") in COMPETITIVE_ROUTES
        assert ("上海", "北京") in COMPETITIVE_ROUTES

    def test_monopoly_routes(self):
        assert ("成都", "拉萨") in MONOPOLY_ROUTES

    def test_budget_routes(self):
        assert ("上海", "石家庄") in BUDGET_ROUTES

    def test_no_overlap(self):
        # A route should not be in both competitive and monopoly
        for route in COMPETITIVE_ROUTES:
            assert route not in MONOPOLY_ROUTES
