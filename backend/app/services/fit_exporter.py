"""Garmin FIT file exporter — converts a Workout record to a binary FIT file."""
import logging
import struct
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# FIT protocol constants
_FIT_EPOCH = 631065600  # seconds between Unix epoch and FIT epoch (1989-12-31)

# FIT message numbers
_MESG_FILE_ID = 0
_MESG_WORKOUT = 26
_MESG_WORKOUT_STEP = 27

# FIT intensity enum values
_INTENSITY_ACTIVE = 0
_INTENSITY_REST = 3
_INTENSITY_WARMUP = 1
_INTENSITY_COOLDOWN = 2

# FIT duration type values
_DURATION_DISTANCE = 1
_DURATION_REPEAT = 6  # repeat_until_steps_cmplt

# FIT target type values
_TARGET_SPEED = 0
_TARGET_OPEN = 1
_TARGET_HR_ZONE = 3

# Pace zone name → (low_pct, high_pct) of VDOT velocity — used as fallback
_ZONE_VELOCITY_RANGES = {
    "easy":      (0.62, 0.70),
    "moderate":  (0.75, 0.84),
    "threshold": (0.86, 0.88),
    "vo2max":    (0.95, 1.00),
    "anaerobic": (1.05, 1.10),
}


def _pace_zone_to_speed_ms(zone_name: str, pace_zones) -> tuple[float, float]:
    """
    Convert a pace zone name to (low_speed_m_per_s, high_speed_m_per_s).

    Uses the pace_zones ORM object if available, otherwise falls back to
    percentage-based estimates from a default VDOT of 40.

    Conversion: speed_m_per_s = 1000 / sec_per_km
    - custom_target_speed_low  = 1000 / max_sec_per_km  (slower pace = lower speed)
    - custom_target_speed_high = 1000 / min_sec_per_km  (faster pace = higher speed)
    """
    zone_name = (zone_name or "easy").lower()

    # Map zone name to (max_sec_attr, min_sec_attr) — max_sec = slower = lower speed
    zone_attr_map = {
        "easy":      ("easy_max_sec_per_km",      "easy_min_sec_per_km"),
        "moderate":  ("moderate_max_sec_per_km",  "moderate_min_sec_per_km"),
        "threshold": ("threshold_max_sec_per_km", "threshold_min_sec_per_km"),
        "vo2max":    ("vo2max_max_sec_per_km",     "vo2max_min_sec_per_km"),
        "anaerobic": ("anaerobic_max_sec_per_km",  "anaerobic_min_sec_per_km"),
    }

    if pace_zones and zone_name in zone_attr_map:
        max_sec_attr, min_sec_attr = zone_attr_map[zone_name]
        max_sec = getattr(pace_zones, max_sec_attr, None)  # slower pace → lower speed
        min_sec = getattr(pace_zones, min_sec_attr, None)  # faster pace → higher speed
        if max_sec and min_sec and max_sec > 0 and min_sec > 0:
            speed_low = 1000.0 / max_sec   # slower pace = lower speed
            speed_high = 1000.0 / min_sec  # faster pace = higher speed
            return (speed_low, speed_high)

    # Fallback: use VDOT=40 reference velocity (~3.33 m/s at 100%)
    ref_v = 3.33
    low_pct, high_pct = _ZONE_VELOCITY_RANGES.get(zone_name, (0.62, 0.70))
    return (ref_v * low_pct, ref_v * high_pct)


def _label_to_intensity(label: str) -> int:
    """Map a step label string to a FIT intensity enum value."""
    label_lower = label.lower()
    # Check for warm-up variants (with or without hyphen)
    if "warm" in label_lower:
        return _INTENSITY_WARMUP
    # Check for cool-down variants (with or without hyphen)
    if "cool" in label_lower:
        return _INTENSITY_COOLDOWN
    # Check for rest/recovery
    if "rest" in label_lower or "recovery" in label_lower:
        return _INTENSITY_REST
    # Default: active
    return _INTENSITY_ACTIVE


# ---------------------------------------------------------------------------
# Raw FIT binary encoding helpers
# ---------------------------------------------------------------------------

def _fit_timestamp(dt: datetime | None = None) -> int:
    """Convert a datetime to FIT timestamp (seconds since FIT epoch)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    unix_ts = int(dt.timestamp())
    return max(0, unix_ts - _FIT_EPOCH)


def _encode_string(s: str, length: int) -> bytes:
    """Encode a string as fixed-length bytes, null-padded."""
    encoded = s.encode("utf-8")[:length]
    return encoded + b"\x00" * (length - len(encoded))


def _crc16(data: bytes) -> int:
    """Calculate FIT CRC-16."""
    crc_table = [
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    ]
    crc = 0
    for byte in data:
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ crc_table[byte & 0xF]
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ crc_table[(byte >> 4) & 0xF]
    return crc


class _FITWriter:
    """Minimal FIT binary file writer."""

    def __init__(self):
        self._records: list[bytes] = []

    def _write_definition(self, local_mesg_num: int, global_mesg_num: int, fields: list[tuple]) -> bytes:
        """
        Write a definition message.
        fields: list of (field_def_num, size, base_type)
        base_type: 0x84=uint16, 0x86=uint32, 0x83=sint32, 0x02=uint8, 0x07=string
        """
        num_fields = len(fields)
        # Definition message header: bit 6 set = definition
        header = 0x40 | local_mesg_num
        # Architecture: 0 = little-endian
        body = struct.pack("<BHB", 0, global_mesg_num, num_fields)
        for field_def_num, size, base_type in fields:
            body += struct.pack("BBB", field_def_num, size, base_type)
        return bytes([header]) + body

    def _write_data(self, local_mesg_num: int, values: list) -> bytes:
        """Write a data message with the given values (pre-packed bytes)."""
        header = local_mesg_num & 0x0F
        body = b"".join(values)
        return bytes([header]) + body

    def add_file_id(self):
        """Add file_id message (type=5 for workout)."""
        fields = [
            (0, 1, 0x02),   # type: uint8
            (4, 4, 0x86),   # time_created: uint32
        ]
        defn = self._write_definition(0, _MESG_FILE_ID, fields)
        self._records.append(defn)

        data = self._write_data(0, [
            struct.pack("<B", 5),                # type=5 (workout)
            struct.pack("<I", _fit_timestamp()), # time_created
        ])
        self._records.append(data)

    def add_workout(self, name: str, sport: int = 1, num_steps: int = 0):
        """Add workout message. sport=1 is running."""
        fields = [
            (4, 1, 0x02),   # sport: uint8
            (5, 4, 0x86),   # capabilities: uint32
            (6, 2, 0x84),   # num_valid_steps: uint16
            (8, 16, 0x07),  # wkt_name: string[16]
        ]
        defn = self._write_definition(1, _MESG_WORKOUT, fields)
        self._records.append(defn)

        data = self._write_data(1, [
            struct.pack("<B", sport),
            struct.pack("<I", 0),           # capabilities
            struct.pack("<H", num_steps),
            _encode_string(name, 16),
        ])
        self._records.append(data)

    def add_workout_step(
        self,
        step_index: int,
        step_name: str,
        duration_distance_m: float,
        target_speed_low: float | None,
        target_speed_high: float | None,
        intensity: int = _INTENSITY_ACTIVE,
        hr_zone: int | None = None,
    ):
        """
        Add a wkt_step message for a distance-based step.

        Args:
            step_index: zero-based wkt_step_index
            step_name: label for the step (truncated to 15 chars)
            duration_distance_m: distance in metres
            target_speed_low: lower speed bound in m/s (None = open target)
            target_speed_high: upper speed bound in m/s (None = open target)
            intensity: FIT intensity enum value
            hr_zone: optional HR zone (1–5); adds secondary HR zone target
        """
        has_speed_target = target_speed_low is not None and target_speed_high is not None

        if has_speed_target:
            # Speed target: target_type=0, custom_target_speed_low/high in mm/s
            speed_low_mms = int(target_speed_low * 1000)
            speed_high_mms = int(target_speed_high * 1000)
            fields = [
                (0, 2, 0x84),   # message_index: uint16
                (1, 16, 0x07),  # wkt_step_name: string[16]
                (2, 4, 0x86),   # duration_value: uint32 (distance in cm)
                (3, 1, 0x02),   # duration_type: uint8
                (4, 4, 0x86),   # target_value: uint32 (speed low mm/s)
                (5, 4, 0x86),   # custom_target_value_low: uint32 (speed low mm/s)
                (6, 4, 0x86),   # custom_target_value_high: uint32 (speed high mm/s)
                (7, 1, 0x02),   # target_type: uint8
                (11, 1, 0x02),  # intensity: uint8
            ]
            defn = self._write_definition(2, _MESG_WORKOUT_STEP, fields)
            self._records.append(defn)

            # distance in cm (FIT uses cm for distance duration type)
            duration_cm = int(duration_distance_m * 100)

            data = self._write_data(2, [
                struct.pack("<H", step_index),
                _encode_string(step_name[:15], 16),
                struct.pack("<I", duration_cm),
                struct.pack("<B", _DURATION_DISTANCE),
                struct.pack("<I", speed_low_mms),   # target_value = low speed
                struct.pack("<I", speed_low_mms),   # custom_target_low
                struct.pack("<I", speed_high_mms),  # custom_target_high
                struct.pack("<B", _TARGET_SPEED),   # target_type=0 (speed)
                struct.pack("<B", intensity),
            ])
            self._records.append(data)
        else:
            # Open target (no pace zone)
            fields = [
                (0, 2, 0x84),   # message_index: uint16
                (1, 16, 0x07),  # wkt_step_name: string[16]
                (2, 4, 0x86),   # duration_value: uint32 (distance in cm)
                (3, 1, 0x02),   # duration_type: uint8
                (4, 4, 0x86),   # target_value: uint32
                (7, 1, 0x02),   # target_type: uint8
                (11, 1, 0x02),  # intensity: uint8
            ]
            defn = self._write_definition(2, _MESG_WORKOUT_STEP, fields)
            self._records.append(defn)

            duration_cm = int(duration_distance_m * 100)

            data = self._write_data(2, [
                struct.pack("<H", step_index),
                _encode_string(step_name[:15], 16),
                struct.pack("<I", duration_cm),
                struct.pack("<B", _DURATION_DISTANCE),
                struct.pack("<I", 0),               # target_value = 0 (open)
                struct.pack("<B", _TARGET_OPEN),    # target_type=1 (open)
                struct.pack("<B", intensity),
            ])
            self._records.append(data)

        # If HR zone is specified, add a secondary HR zone step override
        # Note: FIT secondary target fields (fields 19, 20, 21) are appended
        # as a separate definition when hr_zone is present. Since we already
        # wrote the step above, we use a separate local message number for
        # HR-zone-aware steps to avoid redefining local message 2.
        if hr_zone is not None:
            self._add_hr_zone_override(step_index, hr_zone)

    def _add_hr_zone_override(self, step_index: int, hr_zone: int):
        """
        Append secondary HR zone target fields to the most recently written step.

        FIT secondary target fields for wkt_step:
          field 19: secondary_target_type (uint8) — 3 = heart_rate_zone
          field 20: secondary_custom_target_value_low (uint32) — zone number (1–5)
          field 21: secondary_custom_target_value_high (uint32) — zone number (1–5)
        """
        fields = [
            (0, 2, 0x84),   # message_index: uint16 (to identify which step)
            (19, 1, 0x02),  # secondary_target_type: uint8
            (20, 4, 0x86),  # secondary_custom_target_value_low: uint32
            (21, 4, 0x86),  # secondary_custom_target_value_high: uint32
        ]
        defn = self._write_definition(3, _MESG_WORKOUT_STEP, fields)
        self._records.append(defn)

        data = self._write_data(3, [
            struct.pack("<H", step_index),
            struct.pack("<B", _TARGET_HR_ZONE),  # secondary_target_type=3 (hr_zone)
            struct.pack("<I", hr_zone),           # secondary_custom_target_value_low
            struct.pack("<I", hr_zone),           # secondary_custom_target_value_high
        ])
        self._records.append(data)

    def add_repeat_step(self, step_index: int, repeat_count: int, first_step_index: int):
        """
        Add a repeat wkt_step (duration_type=6 = repeat_until_steps_cmplt).

        Args:
            step_index: zero-based wkt_step_index for this repeat marker
            repeat_count: number of times to repeat the block
            first_step_index: wkt_step_index of the first step in the repeat block
        """
        fields = [
            (0, 2, 0x84),   # message_index: uint16
            (1, 16, 0x07),  # wkt_step_name: string[16]
            (2, 4, 0x86),   # duration_value: uint32 (step index to repeat from)
            (3, 1, 0x02),   # duration_type: uint8
            (4, 4, 0x86),   # target_value: uint32 (repeat count)
            (7, 1, 0x02),   # target_type: uint8
            (11, 1, 0x02),  # intensity: uint8
        ]
        defn = self._write_definition(4, _MESG_WORKOUT_STEP, fields)
        self._records.append(defn)

        data = self._write_data(4, [
            struct.pack("<H", step_index),
            _encode_string("Repeat", 16),
            struct.pack("<I", first_step_index),  # step to repeat from
            struct.pack("<B", _DURATION_REPEAT),  # duration_type=6 (repeat)
            struct.pack("<I", repeat_count),
            struct.pack("<B", _TARGET_OPEN),      # target_type=1 (open)
            struct.pack("<B", _INTENSITY_ACTIVE),
        ])
        self._records.append(data)

    def build(self) -> bytes:
        """Assemble the complete FIT file with header and CRC."""
        body = b"".join(self._records)
        data_size = len(body)

        # FIT file header (14 bytes)
        header = struct.pack(
            "<BBHI4s",
            14,             # header_size
            0x10,           # protocol_version
            2132,           # profile_version (21.32)
            data_size,
            b".FIT",
        )
        header_crc = _crc16(header)
        header += struct.pack("<H", header_crc)

        full_data = header + body
        file_crc = _crc16(full_data)
        return full_data + struct.pack("<H", file_crc)


# ---------------------------------------------------------------------------
# Repeat block detection helpers
# ---------------------------------------------------------------------------

def _count_total_fit_steps(steps: list[dict]) -> int:
    """
    Count the total number of FIT wkt_step messages that will be emitted,
    including repeat marker steps.

    The design encodes repeat blocks using:
    - `repeat_count` on the FIRST step of the block
    - `is_repeat_end` on the LAST step of the block

    A repeat marker step is emitted after each block's last step.
    """
    total = len(steps)
    i = 0
    while i < len(steps):
        step = steps[i]
        if step.get("repeat_count") and step.get("repeat_count", 0) > 1:
            # This step starts a repeat block — find the end
            j = i
            while j < len(steps) and not steps[j].get("is_repeat_end"):
                j += 1
            # One repeat marker will be emitted after the block
            total += 1
            i = j + 1
        else:
            i += 1
    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export(workout, pace_zones) -> bytes:
    """
    Generate a Garmin FIT binary file from a Workout ORM object.

    The generated FIT file contains:
    - file_id message (type=workout)
    - workout message (name, sport=running, num_valid_steps)
    - one wkt_step message per WorkoutStep
    - repeat marker wkt_step messages for interval repeat blocks

    Pace zones are converted from sec/km to m/s:
    - custom_target_speed_low  = 1000 / max_sec_per_km
    - custom_target_speed_high = 1000 / min_sec_per_km

    Repeat blocks are encoded using `repeat_count` on the first step of the
    block and `is_repeat_end` on the last step. A repeat marker wkt_step is
    emitted after the block's last step.

    Args:
        workout: Workout ORM instance with .steps (list of dicts),
                 .workout_type, and .scheduled_date
        pace_zones: PaceZones ORM instance (may be None)

    Returns:
        bytes: FIT file content

    Raises:
        ValueError: if any step is missing distance_metres
    """
    steps = workout.steps or []

    # Validate all steps have distance_metres
    for i, step in enumerate(steps):
        if not step.get("distance_metres"):
            raise ValueError(
                f"Step {i + 1} ('{step.get('label', 'unknown')}') is missing distance_metres"
            )

    writer = _FITWriter()
    writer.add_file_id()

    # Pre-calculate total FIT step count (including repeat markers)
    total_fit_steps = _count_total_fit_steps(steps)

    workout_name = str(workout.workout_type).title()
    writer.add_workout(workout_name, sport=1, num_steps=total_fit_steps)

    fit_step_index = 0
    i = 0
    while i < len(steps):
        step = steps[i]
        distance_m = float(step["distance_metres"])
        zone_name = step.get("pace_zone") or None
        label = step.get("label", f"Step {i + 1}")
        hr_zone = step.get("hr_zone")
        intensity = _label_to_intensity(label)

        # Determine speed target
        if zone_name:
            speed_low, speed_high = _pace_zone_to_speed_ms(zone_name, pace_zones)
        else:
            speed_low, speed_high = None, None

        # Check if this step starts a repeat block
        repeat_count = step.get("repeat_count", 0)
        is_repeat_start = repeat_count and repeat_count > 1

        if is_repeat_start:
            # Record the first step index of the repeat block
            block_first_fit_index = fit_step_index

            # Emit all steps in the repeat block
            j = i
            while j < len(steps):
                block_step = steps[j]
                block_distance_m = float(block_step["distance_metres"])
                block_zone = block_step.get("pace_zone") or None
                block_label = block_step.get("label", f"Step {j + 1}")
                block_hr_zone = block_step.get("hr_zone")
                block_intensity = _label_to_intensity(block_label)

                if block_zone:
                    block_speed_low, block_speed_high = _pace_zone_to_speed_ms(block_zone, pace_zones)
                else:
                    block_speed_low, block_speed_high = None, None

                writer.add_workout_step(
                    step_index=fit_step_index,
                    step_name=block_label[:15],
                    duration_distance_m=block_distance_m,
                    target_speed_low=block_speed_low,
                    target_speed_high=block_speed_high,
                    intensity=block_intensity,
                    hr_zone=block_hr_zone,
                )
                fit_step_index += 1

                if block_step.get("is_repeat_end"):
                    # End of repeat block — emit repeat marker
                    writer.add_repeat_step(
                        step_index=fit_step_index,
                        repeat_count=repeat_count,
                        first_step_index=block_first_fit_index,
                    )
                    fit_step_index += 1
                    i = j + 1
                    break
                j += 1
            else:
                # No is_repeat_end found — treat remaining steps as the block
                # and emit repeat marker after the last step
                writer.add_repeat_step(
                    step_index=fit_step_index,
                    repeat_count=repeat_count,
                    first_step_index=block_first_fit_index,
                )
                fit_step_index += 1
                i = len(steps)
        else:
            # Regular (non-repeat) step
            writer.add_workout_step(
                step_index=fit_step_index,
                step_name=label[:15],
                duration_distance_m=distance_m,
                target_speed_low=speed_low,
                target_speed_high=speed_high,
                intensity=intensity,
                hr_zone=hr_zone,
            )
            fit_step_index += 1
            i += 1

    return writer.build()
