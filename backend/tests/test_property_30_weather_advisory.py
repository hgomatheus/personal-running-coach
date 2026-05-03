"""
Property-based tests for weather advisory threshold correctness.

# Feature: personal-running-coach

**Validates: Requirements 19.3, 19.4**

Property 30: The `build_advisories(forecast)` function SHALL:
  - Include the "heat" advisory if and only if temperature_c > 25 OR humidity_pct > 80
  - Include the "wind" advisory if and only if wind_kmh > 30
  - Include the "rain" advisory if and only if conditions contains "rain"
  - Return an empty list when all values are strictly below thresholds and
    conditions does not contain "rain"
  - Never return a list with duplicate advisory keys

Thresholds (strict inequalities):
  - Heat/humidity: temperature_c > 25  OR  humidity_pct > 80
  - Wind:          wind_kmh > 30
  - Rain:          "rain" in conditions  (substring match)
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.weather_service import WeatherForecast, build_advisories

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Temperature range: -40°C to 60°C (realistic extremes)
_temperature_st = st.floats(
    min_value=-40.0,
    max_value=60.0,
    allow_nan=False,
    allow_infinity=False,
)

# Humidity range: 0–100%
_humidity_st = st.floats(
    min_value=0.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Wind speed range: 0–150 km/h
_wind_st = st.floats(
    min_value=0.0,
    max_value=150.0,
    allow_nan=False,
    allow_infinity=False,
)

# Non-rain condition strings (do not contain "rain")
_non_rain_conditions_st = st.sampled_from(["clear", "cloudy", "snow", "thunderstorm", "fog", ""])

# Rain condition strings (contain "rain")
_rain_conditions_st = st.sampled_from(["rain", "heavy rain", "light rain", "drizzle/rain", "rain/thunderstorm"])

# Any condition string (may or may not contain "rain")
_conditions_st = st.one_of(_non_rain_conditions_st, _rain_conditions_st)


def _make_forecast(
    temperature_c: float = 15.0,
    humidity_pct: float = 50.0,
    wind_kmh: float = 10.0,
    conditions: str = "clear",
) -> WeatherForecast:
    """Helper to construct a WeatherForecast with given values."""
    return WeatherForecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
        cached=False,
    )


# ---------------------------------------------------------------------------
# Property 30a: "heat" advisory is included when temperature_c > 25
# ---------------------------------------------------------------------------


@given(
    temperature_c=st.floats(
        min_value=25.0 + 1e-6,
        max_value=60.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    humidity_pct=st.floats(
        min_value=0.0,
        max_value=80.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    wind_kmh=_wind_st,
    conditions=_conditions_st,
)
@settings(max_examples=100)
def test_heat_advisory_when_temperature_above_threshold(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30a: build_advisories SHALL include "heat" whenever
    temperature_c > 25, regardless of other forecast values.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "heat" in advisories, (
        f"Expected 'heat' advisory for temperature_c={temperature_c} > 25, "
        f"humidity_pct={humidity_pct}. Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30b: "heat" advisory is included when humidity_pct > 80
# ---------------------------------------------------------------------------


@given(
    temperature_c=st.floats(
        min_value=-40.0,
        max_value=25.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    humidity_pct=st.floats(
        min_value=80.0 + 1e-6,
        max_value=100.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    wind_kmh=_wind_st,
    conditions=_conditions_st,
)
@settings(max_examples=100)
def test_heat_advisory_when_humidity_above_threshold(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30b: build_advisories SHALL include "heat" whenever
    humidity_pct > 80, regardless of temperature or other forecast values.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "heat" in advisories, (
        f"Expected 'heat' advisory for humidity_pct={humidity_pct} > 80, "
        f"temperature_c={temperature_c}. Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30c: "heat" advisory is absent when both temperature and humidity
#               are at or below their thresholds
# ---------------------------------------------------------------------------


@given(
    temperature_c=st.floats(
        min_value=-40.0,
        max_value=25.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    humidity_pct=st.floats(
        min_value=0.0,
        max_value=80.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    wind_kmh=_wind_st,
    conditions=_non_rain_conditions_st,
)
@settings(max_examples=100)
def test_no_heat_advisory_when_both_below_threshold(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30c: build_advisories SHALL NOT include "heat" when
    temperature_c ≤ 25 AND humidity_pct ≤ 80.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "heat" not in advisories, (
        f"Did not expect 'heat' advisory for temperature_c={temperature_c} ≤ 25 "
        f"AND humidity_pct={humidity_pct} ≤ 80. Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30d: "wind" advisory is included when wind_kmh > 30
# ---------------------------------------------------------------------------


@given(
    temperature_c=_temperature_st,
    humidity_pct=_humidity_st,
    wind_kmh=st.floats(
        min_value=30.0 + 1e-6,
        max_value=150.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    conditions=_conditions_st,
)
@settings(max_examples=100)
def test_wind_advisory_when_above_threshold(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30d: build_advisories SHALL include "wind" whenever
    wind_kmh > 30, regardless of other forecast values.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "wind" in advisories, (
        f"Expected 'wind' advisory for wind_kmh={wind_kmh} > 30. "
        f"Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30e: "wind" advisory is absent when wind_kmh ≤ 30
# ---------------------------------------------------------------------------


@given(
    temperature_c=_temperature_st,
    humidity_pct=_humidity_st,
    wind_kmh=st.floats(
        min_value=0.0,
        max_value=30.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    conditions=_non_rain_conditions_st,
)
@settings(max_examples=100)
def test_no_wind_advisory_when_at_or_below_threshold(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30e: build_advisories SHALL NOT include "wind" when
    wind_kmh ≤ 30.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "wind" not in advisories, (
        f"Did not expect 'wind' advisory for wind_kmh={wind_kmh} ≤ 30. "
        f"Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30f: "rain" advisory is included when conditions contains "rain"
# ---------------------------------------------------------------------------


@given(
    temperature_c=_temperature_st,
    humidity_pct=_humidity_st,
    wind_kmh=_wind_st,
    conditions=_rain_conditions_st,
)
@settings(max_examples=100)
def test_rain_advisory_when_conditions_contain_rain(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30f: build_advisories SHALL include "rain" whenever the
    conditions string contains "rain" (substring match).

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "rain" in advisories, (
        f"Expected 'rain' advisory for conditions={conditions!r}. "
        f"Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30g: "rain" advisory is absent when conditions does not contain "rain"
# ---------------------------------------------------------------------------


@given(
    temperature_c=_temperature_st,
    humidity_pct=_humidity_st,
    wind_kmh=_wind_st,
    conditions=_non_rain_conditions_st,
)
@settings(max_examples=100)
def test_no_rain_advisory_when_conditions_do_not_contain_rain(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30g: build_advisories SHALL NOT include "rain" when the
    conditions string does not contain "rain".

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert "rain" not in advisories, (
        f"Did not expect 'rain' advisory for conditions={conditions!r}. "
        f"Got advisories: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30h: Empty advisory list when all values are below thresholds
# ---------------------------------------------------------------------------


@given(
    temperature_c=st.floats(
        min_value=-40.0,
        max_value=25.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    humidity_pct=st.floats(
        min_value=0.0,
        max_value=80.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    wind_kmh=st.floats(
        min_value=0.0,
        max_value=30.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    conditions=_non_rain_conditions_st,
)
@settings(max_examples=100)
def test_no_advisories_when_all_below_thresholds(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30h: build_advisories SHALL return an empty list when:
      - temperature_c ≤ 25
      - humidity_pct ≤ 80
      - wind_kmh ≤ 30
      - conditions does not contain "rain"

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert advisories == [], (
        f"Expected empty advisory list for all-below-threshold forecast "
        f"(temp={temperature_c}, humidity={humidity_pct}, wind={wind_kmh}, "
        f"conditions={conditions!r}). Got: {advisories}"
    )


# ---------------------------------------------------------------------------
# Property 30i: Advisory list never contains duplicates
# ---------------------------------------------------------------------------


@given(
    temperature_c=_temperature_st,
    humidity_pct=_humidity_st,
    wind_kmh=_wind_st,
    conditions=_conditions_st,
)
@settings(max_examples=100)
def test_no_duplicate_advisories(
    temperature_c: float,
    humidity_pct: float,
    wind_kmh: float,
    conditions: str,
) -> None:
    """
    Property 30i: build_advisories SHALL never return a list containing
    duplicate advisory keys, for any combination of forecast values.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
    )
    advisories = build_advisories(forecast)

    assert len(advisories) == len(set(advisories)), (
        f"Advisory list contains duplicates: {advisories} "
        f"(temp={temperature_c}, humidity={humidity_pct}, wind={wind_kmh}, "
        f"conditions={conditions!r})"
    )


# ---------------------------------------------------------------------------
# Property 30j: Boundary conditions — exactly at threshold values
# ---------------------------------------------------------------------------


def test_heat_advisory_boundary_temperature_exactly_25() -> None:
    """
    Boundary: temperature_c == 25 (not strictly greater) → no "heat" advisory
    from temperature alone (humidity also at threshold).

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(temperature_c=25.0, humidity_pct=80.0, wind_kmh=0.0, conditions="clear")
    advisories = build_advisories(forecast)
    assert "heat" not in advisories, (
        f"temperature_c=25.0 and humidity_pct=80.0 are at threshold (not above), "
        f"so 'heat' should not be present. Got: {advisories}"
    )


def test_heat_advisory_boundary_temperature_just_above_25() -> None:
    """
    Boundary: temperature_c just above 25 → "heat" advisory IS included.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(temperature_c=25.01, humidity_pct=0.0, wind_kmh=0.0, conditions="clear")
    advisories = build_advisories(forecast)
    assert "heat" in advisories, (
        f"temperature_c=25.01 > 25 should trigger 'heat'. Got: {advisories}"
    )


def test_heat_advisory_boundary_humidity_exactly_80() -> None:
    """
    Boundary: humidity_pct == 80 (not strictly greater) → no "heat" advisory
    from humidity alone (temperature also at threshold).

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(temperature_c=0.0, humidity_pct=80.0, wind_kmh=0.0, conditions="clear")
    advisories = build_advisories(forecast)
    assert "heat" not in advisories, (
        f"humidity_pct=80.0 is at threshold (not above), "
        f"so 'heat' should not be present. Got: {advisories}"
    )


def test_heat_advisory_boundary_humidity_just_above_80() -> None:
    """
    Boundary: humidity_pct just above 80 → "heat" advisory IS included.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(temperature_c=0.0, humidity_pct=80.01, wind_kmh=0.0, conditions="clear")
    advisories = build_advisories(forecast)
    assert "heat" in advisories, (
        f"humidity_pct=80.01 > 80 should trigger 'heat'. Got: {advisories}"
    )


def test_wind_advisory_boundary_exactly_30() -> None:
    """
    Boundary: wind_kmh == 30 (not strictly greater) → no "wind" advisory.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(temperature_c=0.0, humidity_pct=0.0, wind_kmh=30.0, conditions="clear")
    advisories = build_advisories(forecast)
    assert "wind" not in advisories, (
        f"wind_kmh=30.0 is at threshold (not above), "
        f"so 'wind' should not be present. Got: {advisories}"
    )


def test_wind_advisory_boundary_just_above_30() -> None:
    """
    Boundary: wind_kmh just above 30 → "wind" advisory IS included.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(temperature_c=0.0, humidity_pct=0.0, wind_kmh=30.01, conditions="clear")
    advisories = build_advisories(forecast)
    assert "wind" in advisories, (
        f"wind_kmh=30.01 > 30 should trigger 'wind'. Got: {advisories}"
    )


def test_all_three_advisories_when_all_thresholds_exceeded() -> None:
    """
    When all thresholds are exceeded simultaneously, all three advisories
    SHALL be present.

    **Validates: Requirements 19.3, 19.4**
    """
    forecast = _make_forecast(
        temperature_c=30.0,
        humidity_pct=90.0,
        wind_kmh=50.0,
        conditions="rain",
    )
    advisories = build_advisories(forecast)

    assert "heat" in advisories, f"Expected 'heat' in {advisories}"
    assert "rain" in advisories, f"Expected 'rain' in {advisories}"
    assert "wind" in advisories, f"Expected 'wind' in {advisories}"
    assert len(advisories) == len(set(advisories)), f"Duplicates found: {advisories}"
