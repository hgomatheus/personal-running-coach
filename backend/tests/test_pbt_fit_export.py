"""
Property-based tests for FIT file export.

# Feature: personal-running-coach

**Validates: Requirements 17.2, 17.3, 17.4**

Property 28: FitExporter.export(workout, pace_zones) SHALL produce a FIT file where:
  1. The number of wkt_step messages equals the number of WorkoutSteps in the
     workout plus any repeat marker steps for interval blocks.
  2. The sum of duration_distance values across all non-repeat wkt_step messages
     equals the sum of distance_metres across all WorkoutSteps in the workout.
"""

import io
import struct
from dataclasses import dataclass, field
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.fit_exporter import _count_total_fit_steps, export

# ---------------------------------------------------------------------------
# FIT protocol constants (mirrors fit_exporter.py)
# ---------------------------------------------------------------------------

_FIT_EPOCH = 631065600
_MESG_WORKOUT_STEP = 27
_DURATION_DISTANCE = 1   # distance-based step
_DURATION_REPEAT = 6     # repeat_until_steps_cmplt


# ---------------------------------------------------------------------------
# Minimal FIT binary parser
# ---------------------------------------------------------------------------

def _parse_fit_wkt_steps(fit_bytes: bytes) -> list[dict]:
    """
    Parse a FIT binary file and return a list of wkt_step message dicts.

    Each dict contains the fields that were defined for that message:
      - 'message_index': int (field 0)
      - 'duration_value': int (field 2) — distance in cm for distance steps
      - 'duration_type': int (field 3) — 1=distance, 6=repeat
      - 'target_value': int (field 4)
      - 'target_type': int (field 7)
      - 'intensity': int (field 11)

    This parser handles the definition/data message pattern used by
    fit_exporter.py. It only extracts wkt_step (global message 27) records.

    Note: fit_exporter._write_definition uses struct.pack("<BHB", reserved,
    global_mesg_num, num_fields) — 4 bytes total (no architecture byte).
    """
    # Skip the 14-byte FIT file header (header_size + protocol + profile +
    # data_size + ".FIT" + header_crc)
    if len(fit_bytes) < 14:
        return []

    header_size = fit_bytes[0]
    data = fit_bytes[header_size:]  # skip header (including 2-byte header CRC)

    # local_mesg_num → {field_def_num: (offset_in_record, size)}
    local_definitions: dict[int, dict] = {}
    # local_mesg_num → global_mesg_num
    local_global_map: dict[int, int] = {}
    # local_mesg_num → total record data size (sum of field sizes)
    local_data_sizes: dict[int, int] = {}

    wkt_steps: list[dict] = []
    pos = 0

    while pos < len(data) - 2:  # -2 for trailing file CRC
        if pos >= len(data):
            break

        record_header = data[pos]
        pos += 1

        is_definition = bool(record_header & 0x40)
        local_mesg_num = record_header & 0x0F

        if is_definition:
            # Definition message body: reserved(1B) + global_mesg_num(2B) + num_fields(1B)
            # fit_exporter uses struct.pack("<BHB", 0, global_mesg_num, num_fields)
            if pos + 4 > len(data):
                break
            _reserved = data[pos]
            global_mesg_num = struct.unpack_from("<H", data, pos + 1)[0]
            num_fields = data[pos + 3]
            pos += 4

            field_defs: dict[int, tuple] = {}  # field_def_num → (offset_in_record, size)
            total_size = 0
            for _ in range(num_fields):
                if pos + 3 > len(data):
                    break
                fdef_num = data[pos]
                fsize = data[pos + 1]
                _base_type = data[pos + 2]
                field_defs[fdef_num] = (total_size, fsize)
                total_size += fsize
                pos += 3

            local_definitions[local_mesg_num] = field_defs
            local_global_map[local_mesg_num] = global_mesg_num
            local_data_sizes[local_mesg_num] = total_size

        else:
            # Data message
            if local_mesg_num not in local_definitions:
                break

            total_size = local_data_sizes.get(local_mesg_num, 0)
            if pos + total_size > len(data):
                break

            record_data = data[pos: pos + total_size]
            pos += total_size

            global_mesg_num = local_global_map.get(local_mesg_num, -1)
            if global_mesg_num != _MESG_WORKOUT_STEP:
                continue

            # Extract fields we care about
            field_defs = local_definitions[local_mesg_num]
            step: dict[str, Any] = {}

            def _read_field(fdef_num: int, _fd=field_defs, _rd=record_data) -> int | None:
                if fdef_num not in _fd:
                    return None
                offset, size = _fd[fdef_num]
                if offset + size > len(_rd):
                    return None
                raw = _rd[offset: offset + size]
                if size == 1:
                    return struct.unpack_from("<B", raw)[0]
                elif size == 2:
                    return struct.unpack_from("<H", raw)[0]
                elif size == 4:
                    return struct.unpack_from("<I", raw)[0]
                return None

            step["message_index"] = _read_field(0)
            step["duration_value"] = _read_field(2)
            step["duration_type"] = _read_field(3)
            step["target_value"] = _read_field(4)
            step["target_type"] = _read_field(7)
            step["intensity"] = _read_field(11)

            wkt_steps.append(step)

    return wkt_steps


# ---------------------------------------------------------------------------
# Minimal mock objects for Workout and PaceZones
# ---------------------------------------------------------------------------

@dataclass
class _MockPaceZones:
    """Minimal PaceZones-like object with sec/km attributes."""
    easy_min_sec_per_km: int = 360      # 6:00/km
    easy_max_sec_per_km: int = 420      # 7:00/km
    moderate_min_sec_per_km: int = 300  # 5:00/km
    moderate_max_sec_per_km: int = 360  # 6:00/km
    threshold_min_sec_per_km: int = 270 # 4:30/km
    threshold_max_sec_per_km: int = 300 # 5:00/km
    vo2max_min_sec_per_km: int = 240    # 4:00/km
    vo2max_max_sec_per_km: int = 270    # 4:30/km
    anaerobic_min_sec_per_km: int = 210 # 3:30/km
    anaerobic_max_sec_per_km: int = 240 # 4:00/km


@dataclass
class _MockWorkout:
    """Minimal Workout-like object for FIT export."""
    workout_type: str
    steps: list[dict]
    scheduled_date: Any = None


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid pace zone names
_pace_zone_st = st.sampled_from(["easy", "moderate", "threshold", "vo2max", "anaerobic"])

# Valid distance per step: 100 m to 42,195 m
_distance_st = st.floats(
    min_value=100.0,
    max_value=42_195.0,
    allow_nan=False,
    allow_infinity=False,
)

# Step label strategy
_label_st = st.sampled_from([
    "Warm-up", "Cool-down", "Run", "Interval", "Recovery", "Hill Repeat",
    "Easy Run", "Tempo", "Step 1",
])

# A single non-repeat WorkoutStep dict
_simple_step_st = st.fixed_dictionaries({
    "sequence": st.integers(min_value=1, max_value=20),
    "label": _label_st,
    "distance_metres": _distance_st,
    "pace_zone": _pace_zone_st,
    "hr_zone": st.none(),
})

# A list of 1–10 simple (non-repeat) WorkoutSteps
_simple_steps_st = st.lists(
    _simple_step_st,
    min_size=1,
    max_size=10,
)

# Workout type strategy
_workout_type_st = st.sampled_from([
    "easy", "tempo", "interval", "hills", "long", "race", "recovery",
])

# A repeat block: 2–5 steps with repeat_count on the first and is_repeat_end on the last
def _make_repeat_block_st(repeat_count: int):
    """Strategy that generates a repeat block of 2–5 steps."""
    return st.lists(
        _simple_step_st,
        min_size=2,
        max_size=5,
    ).map(lambda steps: _annotate_repeat_block(steps, repeat_count))


def _annotate_repeat_block(steps: list[dict], repeat_count: int) -> list[dict]:
    """Add repeat_count to first step and is_repeat_end to last step."""
    result = [dict(s) for s in steps]
    result[0]["repeat_count"] = repeat_count
    result[-1]["is_repeat_end"] = True
    return result


# A workout with only simple steps (no repeat blocks)
_simple_workout_st = st.builds(
    lambda wtype, steps: _MockWorkout(workout_type=wtype, steps=steps),
    wtype=_workout_type_st,
    steps=_simple_steps_st,
)

# A workout with a single repeat block (2–3 repeats) surrounded by optional simple steps
_repeat_workout_st = st.builds(
    lambda wtype, pre, block, post: _MockWorkout(
        workout_type=wtype,
        steps=pre + block + post,
    ),
    wtype=_workout_type_st,
    pre=st.lists(_simple_step_st, min_size=0, max_size=3),
    block=st.integers(min_value=2, max_value=5).flatmap(_make_repeat_block_st),
    post=st.lists(_simple_step_st, min_size=0, max_size=3),
)

# Combined workout strategy: either simple or with a repeat block
_workout_st = st.one_of(_simple_workout_st, _repeat_workout_st)


# ---------------------------------------------------------------------------
# Helper: count expected FIT steps
# ---------------------------------------------------------------------------

def _expected_fit_step_count(steps: list[dict]) -> int:
    """
    Compute the expected total number of FIT wkt_step messages for a given
    list of WorkoutStep dicts. Mirrors the logic in _count_total_fit_steps().

    For simple steps: 1 FIT step per WorkoutStep.
    For repeat blocks: N steps in block + 1 repeat marker step.
    """
    return _count_total_fit_steps(steps)


def _expected_distance_sum_cm(steps: list[dict]) -> float:
    """
    Compute the expected sum of duration_distance values (in cm) across all
    non-repeat wkt_step messages. This equals the sum of distance_metres
    across all WorkoutSteps converted to cm (× 100).
    """
    return sum(float(s["distance_metres"]) * 100 for s in steps)


# ---------------------------------------------------------------------------
# Property 28a: wkt_step count matches WorkoutStep count + repeat markers
# ---------------------------------------------------------------------------


@given(workout=_workout_st)
@settings(max_examples=100)
def test_fit_step_count_matches_workout_steps(workout: _MockWorkout):
    """
    Property 28a: FitExporter.export(workout, pace_zones) SHALL produce a FIT
    file where the number of wkt_step messages equals the number of WorkoutSteps
    in the workout plus any repeat marker steps for interval blocks.

    For a workout with N simple steps: exactly N wkt_step messages.
    For a workout with a repeat block of M steps: M + 1 wkt_step messages
    (M regular steps + 1 repeat marker), plus any surrounding simple steps.

    **Validates: Requirements 17.2, 17.4**
    """
    pace_zones = _MockPaceZones()
    fit_bytes = export(workout, pace_zones)

    wkt_steps = _parse_fit_wkt_steps(fit_bytes)
    actual_count = len(wkt_steps)
    expected_count = _expected_fit_step_count(workout.steps)

    assert actual_count == expected_count, (
        f"FIT file contains {actual_count} wkt_step messages, "
        f"expected {expected_count}. "
        f"Workout steps: {len(workout.steps)}, "
        f"steps detail: {workout.steps}"
    )


# ---------------------------------------------------------------------------
# Property 28b: distance sum of non-repeat steps matches WorkoutStep distances
# ---------------------------------------------------------------------------


@given(workout=_workout_st)
@settings(max_examples=100)
def test_fit_distance_sum_matches_workout_steps(workout: _MockWorkout):
    """
    Property 28b: FitExporter.export(workout, pace_zones) SHALL produce a FIT
    file where the sum of duration_distance values across all non-repeat
    wkt_step messages equals the sum of distance_metres across all WorkoutSteps
    in the workout.

    duration_distance is stored in cm (distance_metres × 100). The comparison
    uses integer cm values to avoid floating-point precision issues.

    **Validates: Requirements 17.2, 17.3**
    """
    pace_zones = _MockPaceZones()
    fit_bytes = export(workout, pace_zones)

    wkt_steps = _parse_fit_wkt_steps(fit_bytes)

    # Sum duration_value (in cm) for non-repeat steps only
    actual_distance_sum_cm = sum(
        s["duration_value"]
        for s in wkt_steps
        if s.get("duration_type") == _DURATION_DISTANCE
        and s.get("duration_value") is not None
    )

    # Expected: sum of all step distances in cm (truncated to int, as the
    # exporter uses int(distance_m * 100))
    expected_distance_sum_cm = sum(
        int(float(s["distance_metres"]) * 100)
        for s in workout.steps
    )

    assert actual_distance_sum_cm == expected_distance_sum_cm, (
        f"FIT distance sum = {actual_distance_sum_cm} cm, "
        f"expected {expected_distance_sum_cm} cm. "
        f"Difference: {actual_distance_sum_cm - expected_distance_sum_cm} cm. "
        f"Workout steps: {workout.steps}"
    )


# ---------------------------------------------------------------------------
# Property 28c: repeat steps have duration_type = REPEAT (6), not DISTANCE (1)
# ---------------------------------------------------------------------------


@given(
    pre=st.lists(_simple_step_st, min_size=0, max_size=3),
    block=st.integers(min_value=2, max_value=5).flatmap(_make_repeat_block_st),
    post=st.lists(_simple_step_st, min_size=0, max_size=3),
)
@settings(max_examples=100)
def test_fit_repeat_steps_have_correct_duration_type(
    pre: list[dict],
    block: list[dict],
    post: list[dict],
):
    """
    Property 28c: For workouts with interval repeat blocks, the FIT file SHALL
    contain exactly one wkt_step message with duration_type=6 (repeat) per
    repeat block. All other wkt_step messages SHALL have duration_type=1
    (distance).

    **Validates: Requirements 17.4**
    """
    steps = pre + block + post
    workout = _MockWorkout(workout_type="interval", steps=steps)
    pace_zones = _MockPaceZones()

    fit_bytes = export(workout, pace_zones)
    wkt_steps = _parse_fit_wkt_steps(fit_bytes)

    repeat_steps = [s for s in wkt_steps if s.get("duration_type") == _DURATION_REPEAT]
    distance_steps = [s for s in wkt_steps if s.get("duration_type") == _DURATION_DISTANCE]

    # There should be exactly 1 repeat marker step (one repeat block)
    assert len(repeat_steps) == 1, (
        f"Expected exactly 1 repeat marker step, got {len(repeat_steps)}. "
        f"All steps: {wkt_steps}"
    )

    # All non-repeat steps should have duration_type=DISTANCE
    non_repeat_non_distance = [
        s for s in wkt_steps
        if s.get("duration_type") not in (_DURATION_DISTANCE, _DURATION_REPEAT)
    ]
    assert len(non_repeat_non_distance) == 0, (
        f"Found {len(non_repeat_non_distance)} steps with unexpected duration_type: "
        f"{non_repeat_non_distance}"
    )

    # Number of distance steps = total steps in workout (all WorkoutSteps have distance)
    assert len(distance_steps) == len(steps), (
        f"Expected {len(steps)} distance steps (one per WorkoutStep), "
        f"got {len(distance_steps)}. "
        f"Total wkt_steps: {len(wkt_steps)}"
    )


# ---------------------------------------------------------------------------
# Property 28d: ValueError raised when any step is missing distance_metres
# ---------------------------------------------------------------------------


@given(
    steps=st.lists(_simple_step_st, min_size=1, max_size=10),
    missing_idx=st.integers(min_value=0, max_value=9),
)
@settings(max_examples=100)
def test_fit_export_raises_on_missing_distance(
    steps: list[dict],
    missing_idx: int,
):
    """
    Property 28d: FitExporter.export() SHALL raise ValueError if any
    WorkoutStep is missing distance_metres (None or 0).

    **Validates: Requirements 17.10**
    """
    import pytest

    # Clamp missing_idx to valid range
    idx = missing_idx % len(steps)

    # Remove distance_metres from one step
    bad_steps = [dict(s) for s in steps]
    bad_steps[idx] = {k: v for k, v in bad_steps[idx].items() if k != "distance_metres"}

    workout = _MockWorkout(workout_type="easy", steps=bad_steps)
    pace_zones = _MockPaceZones()

    with pytest.raises(ValueError, match="distance_metres"):
        export(workout, pace_zones)
